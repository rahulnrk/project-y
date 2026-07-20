"""
pipeline.py - B2C voice pipeline with tight conversation context.
"""

import aiohttp
from datetime import datetime, timedelta, timezone

from loguru import logger
from openai import AsyncOpenAI

from pipecat.audio.vad.silero import SileroVADAnalyzer
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
from ..utils.latency_tracker import LatencyTracker
from ..utils.prompt_manager import get_prompt
from .language_switch import LanguageSwitchProcessor
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
        "ChatGPT-Voice style: precise, fluid, human. "
        "Answer the latest user message only. Stay on-topic. No re-introductions."
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

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            serializer=serializer,
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            audio_out_10ms_chunks=8,
        ),
    )

    _vad = SileroVADAnalyzer()
    aiohttp_session = aiohttp.ClientSession()

    # hi-IN + codemix is far more stable than language=unknown (which mis-tagged
    # Punjabi/Malayalam and polluted context). Switch STT on language change.
    stt_language = profile.language or DEFAULT_LANGUAGE
    stt = SarvamSTTService(
        api_key=SARVAM_API_KEY,
        mode="codemix",
        settings=SarvamSTTService.Settings(
            model="saaras:v3",
            language=stt_language,
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
            loudness=1.9,
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
            max_tokens=180,
            temperature=0.45,
            extra={"reasoning_effort": None},
        ),
    )

    safety = SafetyGuardrailProcessor()
    utterance_buffer = FullUtteranceBuffer()
    transcript_filter = TranscriptFilter(min_chars=2)

    system_prompt = _build_system_prompt(profile)
    print(f"[pipeline] context-aware | lang={tts_language} | {_india_now_blob()}")

    # ONE system message only (no sticky "ask name" injects)
    context = LLMContext(messages=[{"role": "system", "content": system_prompt}])
    lang_switch = LanguageSwitchProcessor(
        profile, context, tts_service=tts, stt_service=stt
    )

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_filter,
            lang_switch,
            safety,
            context_aggregator.user(),
            llm,
            utterance_buffer,
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
        if not profile.name or profile.total_calls <= 1:
            cue = (
                "(Call connected. Open like ChatGPT Voice: warm natural Hindi, one fluid line — "
                "you're Sahaay, ask my name casually. Sound human, not IVR. Never re-introduce later.)"
            )
        else:
            name = profile.name or "dost"
            cue = (
                f"(Call connected. Open like ChatGPT Voice: warm natural Hindi greeting for {name}, "
                f"one fluid line, ready to listen. Human, not IVR. No re-intro later.)"
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

    print(f"[METRICS] Call ended for {phone_number} | {tracker.get_summary()}")

    full_transcript = "\n".join(
        f"{m.get('role')}: {m.get('content')}"
        for m in context.get_messages()
        if m.get("role") in ("user", "assistant")
        and not str(m.get("content", "")).startswith("(Call just connected")
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
