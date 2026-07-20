"""
pipeline.py - B2C voice pipeline with tight conversation context.
"""

import aiohttp
from datetime import datetime, timedelta, timezone

from loguru import logger
from openai import AsyncOpenAI

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamHttpTTSService, SarvamHttpTTSSettings
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.turns.user_mute import MuteUntilFirstBotCompleteUserMuteStrategy

from ..config import (
    SARVAM_API_KEY,
    SARVAM_LLM_BASE_URL,
    SARVAM_LLM_MODEL,
    DEFAULT_VOICE,
    DEFAULT_LANGUAGE,
    EXOTEL_SAMPLE_RATE,
)
from ..guardrails.processor import SafetyGuardrailProcessor
from ..memory.memory_store import MemoryStore, summarize_call
from ..services.web_search import NewsInjectProcessor
from ..utils.call_log import BotTurnTap, CallLog, UserTurnTap
from ..utils.latency_tracker import LatencyTracker
from ..utils.prompt_manager import get_prompt
from .language_switch import CALL_CUE_PREFIX, LanguageSwitchProcessor
from .transcript_filter import TranscriptFilter
from .utterance_buffer import FullUtteranceBuffer

_IST = timezone(timedelta(hours=5, minutes=30), name="IST")

_LANG_LABELS = {
    "hi-IN": "Hindi (not Marathi)",
    "te-IN": "Telugu",
    "en-IN": "English (India)",
}

# Sarvam bulbul:v2 always emits 22050 Hz WAV (verified); do not label as 8k.
SARVAM_NATIVE_SR = 22050


def _india_now_blob() -> str:
    now = datetime.now(_IST)
    clock_12 = now.strftime("%I:%M %p").lstrip("0")
    return (
        f"REAL TIME NOW (India IST): {now.strftime('%A, %d %B %Y')}, {clock_12} "
        f"(24h {now.strftime('%H:%M')}). Use only this for time questions."
    )


def _build_system_prompt(profile) -> str:
    lang_code = profile.language or DEFAULT_LANGUAGE
    lang_label = _LANG_LABELS.get(lang_code, lang_code)
    # Keep profile memory light so old call topics do not dominate
    context = profile.to_context_blob()
    time_blob = _india_now_blob()

    template = get_prompt("system_prompt.txt") or get_prompt("voice/system_prompt.txt")
    if template:
        prompt = template.replace("{context_blob}", f"{context}\n\n{time_blob}")
    else:
        prompt = (
            f"You are Sahaay on a phone call. Answer only the latest user message. "
            f"Speak {lang_label}. One short sentence. {context}\n{time_blob}"
        )

    prompt += (
        f"\n\nACTIVE LANGUAGE: {lang_label} ({lang_code}). "
        "Reply in the language the caller is currently speaking. If they switch "
        "language mid-call, switch with them immediately and keep speaking that "
        "language for the rest of the call -- do not drift back. Never announce "
        "the switch. Keep technical, business and product words in English even "
        "inside a Hindi or Telugu sentence; that is how bilingual Indians talk. "
        "ChatGPT-Voice style: precise, fluid, human. "
        "LENGTH: two or three natural spoken sentences is the sweet spot. Be "
        "brief, never blunt -- a bare one-word reply like 'Sahaay.' or 'Rahul.' "
        "sounds cold and robotic. Answer, then add one short piece of substance "
        "or a natural follow-up, the way a friend would. Never read out a list "
        "of more than two items. "
        "If the caller says they cannot hear you, your voice is breaking, or "
        "asks you to repeat: apologise ONCE in your own words, then actually "
        "repeat your last point more slowly and clearly. Never reply with the "
        "same apology twice -- that is what makes you sound broken. "
        "NEVER ask what help they want. Not in any language -- not 'how can I "
        "help', not 'मैं आपकी क्या मदद कर सकता हूँ', not 'మీరేమి సహాయం "
        "చేయాలనుకుంటున్నారు'. They called to talk. If there is nothing "
        "specific, just be good company: ask about their day, or follow the "
        "thread they already started. Asking again after they have said they "
        "want nothing is the single most irritating thing you can do. "
        "If their sentence sounds cut off or trails away, do NOT answer it and "
        "do NOT repeat yourself -- invite them to finish ('చెప్పండి, "
        "వింటున్నాను', 'haan boliye') and wait. "
        "Say money and numbers the spoken way (Rs 1.50 is 'one rupee fifty', "
        "2026 is a year, not digits). "
        "Answer the latest user message only. Stay on-topic. No re-introductions. "
        "NEVER ask for their phone number -- you are already on a call with them "
        "and the system knows their number. Never ask for OTPs, PINs, or IDs. "
        "Never re-ask something the caller just told you, and never repeat your "
        "previous reply -- each turn must move the conversation forward. If they "
        "already answered your question, build on their answer. "
        "CURRENT EVENTS: when a system message titled LIVE SEARCH RESULTS is "
        "present, it is real fetched data -- answer from it naturally. When it "
        "is absent and they ask for news, prices, scores or weather, say in one "
        "line that you could not check right now -- never invent headlines, "
        "numbers or dates. "
        "This is a mobile call in India, so audio may break up. If a message "
        "looks garbled or half-heard, do not guess: ask them warmly to say it "
        "once more, in their language, without sounding annoyed."
    )
    return prompt


async def build_b2c_pipeline(
    websocket,
    stream_sid: str,
    call_sid: str,
    phone_number: str,
    profile,
    memory: MemoryStore,
):
    tracker = LatencyTracker()

    serializer = ExotelFrameSerializer(stream_sid=stream_sid, call_sid=call_sid)

    # VAD must be handed to the transport params. Constructing the analyzer
    # alone does nothing: without it here the transport never emits
    # User{Started,Stopped}SpeakingFrame, so interruptions never fire and the
    # caller cannot barge in (it reads as an answering machine).
    #
    # stop_secs is deliberately longer than the pipecat default (~0.8s):
    # Hindi/Telugu speakers pause mid-sentence, and aggressive silence-based
    # endpointing cuts them off. Tune this first if callers get clipped.
    # stop_secs raised 1.1 -> 1.5. On a live call the caller was cut off
    # mid-sentence ("...chicken తిన్నాను దాని తర్వాత" -- clearly continuing),
    # and feeding the model a fragment is what triggered it to echo its own
    # previous reply. Indian-language speakers pause mid-thought; the pipecat
    # default of 0.2s is far too aggressive for this.
    vad_analyzer = SileroVADAnalyzer(
        params=VADParams(stop_secs=1.5, start_secs=0.2, confidence=0.7)
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            serializer=serializer,
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            # 4 x 10ms = 40ms (pipecat default). Was 8 (80ms), which delivers
            # audio in larger bursts and reads as choppy on a mobile network.
            audio_out_10ms_chunks=4,
            vad_analyzer=vad_analyzer,
        ),
    )

    aiohttp_session = aiohttp.ClientSession()

    # Auto-detect, not pinned. Pinning to the profile language (hi-IN) meant a
    # caller speaking Telugu or English was transcribed as Hindi, so the model
    # never even saw the right words -- no prompt rule can recover from that.
    # saaras:v3 takes language="unknown" for per-utterance detection.
    #
    # Auto-detect previously caused Punjabi/Malayalam mis-tags to pollute
    # context. Two guards now contain that: LanguageSwitchProcessor only ever
    # switches to hi/te/en, and requires consecutive agreeing detections.
    stt = SarvamSTTService(
        api_key=SARVAM_API_KEY,
        mode="codemix",
        settings=SarvamSTTService.Settings(
            model="saaras:v3",
            language="unknown",
        ),
    )

    voice_id = profile.voice_id or DEFAULT_VOICE
    tts_language = profile.language or DEFAULT_LANGUAGE
    # Warm, clear voice; slightly unhurried pace reads more human on phone.
    tts = SarvamHttpTTSService(
        api_key=SARVAM_API_KEY,
        aiohttp_session=aiohttp_session,
        sample_rate=SARVAM_NATIVE_SR,
        aggregate_sentences=False,
        settings=SarvamHttpTTSSettings(
            voice=voice_id,
            model="bulbul:v2",
            language=tts_language,
            pace=0.96,
            # loudness was 1.9 (range is 0.3-3.0, neutral 1.0). Measured against
            # the live API on a sample line: 1.9 -> 815 hard-clipped samples at
            # 22kHz and 266 surviving the 8kHz downsample; 1.0 -> 2 and 0.
            # Clipping is what makes the voice sound distorted / "not clear" on
            # a phone, and it gets worse through telephony resampling.
            loudness=1.0,
            pitch=0.0,
            enable_preprocessing=True,
        ),
    )

    # A bit more room + warmth than "strict IVR mode", still precise.
    llm = SarvamLLMService(
        api_key=SARVAM_API_KEY,
        base_url=SARVAM_LLM_BASE_URL,
        settings=SarvamLLMService.Settings(
            model=SARVAM_LLM_MODEL,
            max_tokens=220,
            temperature=0.6,
            extra={
                "reasoning_effort": None,
                # On a live call the model repeated "Oh, sorry about that."
                # verbatim across four turns and "Hmm, क्या बात है?" across
                # three -- with the full history visible in context, so it was
                # ignoring the prompt's anti-repetition rule. Penalties enforce
                # variety at decode time instead of asking nicely. Verified
                # accepted by the Sarvam OpenAI-compatible endpoint.
                "frequency_penalty": 0.5,
                "presence_penalty": 0.4,
            },
        ),
    )

    safety = SafetyGuardrailProcessor()
    utterance_buffer = FullUtteranceBuffer(
        language_getter=lambda: profile.language or DEFAULT_LANGUAGE
    )
    transcript_filter = TranscriptFilter(min_chars=2)

    # Per-call JSONL event log -- read by the /dashboard routes.
    call_log = CallLog(call_sid=call_sid, phone_number=phone_number)
    user_tap = UserTurnTap(call_log)
    bot_tap = BotTurnTap(call_log)

    system_prompt = _build_system_prompt(profile)
    print(f"[pipeline] context-aware | lang={tts_language} | {_india_now_blob()}")

    # ONE system message only (no sticky "ask name" injects)
    context = LLMContext(messages=[{"role": "system", "content": system_prompt}])
    # Pass the builder (not the built string) so a mid-call switch regenerates
    # the base prompt against the updated profile.language.
    lang_switch = LanguageSwitchProcessor(
        profile,
        context,
        tts_service=tts,
        stt_service=stt,
        system_prompt_builder=lambda: _build_system_prompt(profile),
    )
    lang_switch.call_log = call_log

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )

    # Live current-events data. Placed AFTER lang_switch so each turn's scrub
    # (which drops last turn's LIVE SEARCH RESULTS) runs before fresh results
    # are injected for this turn.
    news_inject = NewsInjectProcessor(context, profile, aiohttp_session)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_filter,
            user_tap,               # log user turns + detected language
            lang_switch,
            news_inject,
            safety,
            context_aggregator.user(),
            llm,
            utterance_buffer,
            bot_tap,                # log bot speech
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=EXOTEL_SAMPLE_RATE,
            audio_out_sample_rate=EXOTEL_SAMPLE_RATE,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Caller connected: {phone_number}")
        # One-shot user cue — ChatGPT-Voice style natural open, not sticky system rule
        # Both branches MUST start with CALL_CUE_PREFIX so LanguageSwitchProcessor
        # can scrub this one-shot cue out of context after the first turn.
        # Greeting language follows the profile instead of being hardcoded Hindi.
        greet_lang = _LANG_LABELS.get(profile.language or DEFAULT_LANGUAGE, "Hindi")
        if not profile.name or profile.total_calls <= 1:
            cue = (
                f"{CALL_CUE_PREFIX} Open like ChatGPT Voice: warm natural {greet_lang}, "
                "one short fluid line — you're Sahaay, ask my name casually. Sound human, "
                "not IVR. Never re-introduce later.)"
            )
        else:
            name = profile.name or "dost"
            cue = (
                f"{CALL_CUE_PREFIX} Open like ChatGPT Voice: warm natural {greet_lang} greeting "
                f"for {name}, one short fluid line, ready to listen. Human, not IVR. "
                f"No re-intro later.)"
            )
        context.add_message({"role": "user", "content": cue})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Caller disconnected: {phone_number}")
        await task.cancel()

    runner = PipelineRunner()
    try:
        await runner.run(task)
    finally:
        await aiohttp_session.close()

    summary_metrics = tracker.get_summary()
    call_log.event("call_ended", lang=profile.language, **summary_metrics)
    print(f"[METRICS] Call ended for {phone_number} | {summary_metrics}")

    full_transcript = "\n".join(
        f"{m.get('role')}: {m.get('content')}"
        for m in context.get_messages()
        if m.get("role") in ("user", "assistant")
        and not str(m.get("content", "")).startswith(CALL_CUE_PREFIX)
    )
    if not full_transcript.strip():
        return

    try:
        summarizer_client = AsyncOpenAI(
            api_key=SARVAM_API_KEY,
            base_url=SARVAM_LLM_BASE_URL,
            default_headers={"api-subscription-key": SARVAM_API_KEY} if SARVAM_API_KEY else None,
            timeout=20.0,
        )

        async def _summarize_with_fast_model(prompt: str) -> str:
            response = await summarizer_client.chat.completions.create(
                model=SARVAM_LLM_MODEL,
                messages=[
                    {"role": "system", "content": "Return valid JSON only. No markdown fences."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=400,
                extra_body={"reasoning_effort": None},
            )
            return response.choices[0].message.content or ""

        new_summary, new_facts = await summarize_call(
            _summarize_with_fast_model, full_transcript, profile.rolling_summary
        )
        await memory.append_call_summary(phone_number, new_facts, new_summary)
        print(f"[MEMORY] Updated {phone_number}: {new_summary[:80]}...")
    except Exception as e:
        logger.warning(f"Post-call memory update skipped: {e}")
