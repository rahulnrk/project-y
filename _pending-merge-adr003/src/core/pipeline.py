"""
pipeline.py - Main Pipecat pipeline builder for B2C voice assistant
Includes: STT → Safety → Onboarding/Memory → LLM → TTS

LLM path is Sarvam (OpenAI-compatible). OpenAI is not required on the live path.

ADR-003 implementation: VAD wiring + interruptions + full LatencyTracker instrumentation
+ safety priority handling coordination + ADR-004 measurement events.
"""

import time
import aiohttp
from openai import AsyncOpenAI

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamHttpTTSService, SarvamHttpTTSSettings
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.frames.frames import (
    Frame,
    UserStoppedSpeakingFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    InterruptionFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection

from ..config import (
    SARVAM_API_KEY,
    SARVAM_LLM_BASE_URL,
    SARVAM_LLM_MODEL,
    DEFAULT_VOICE,
    EXOTEL_SAMPLE_RATE,
)
from ..guardrails.processor import SafetyGuardrailProcessor
from ..memory.memory_store import MemoryStore, summarize_call
from ..utils.latency_tracker import LatencyTracker
from ..utils.prompt_manager import get_prompt


async def build_b2c_pipeline(
    websocket,
    stream_sid: str,
    call_sid: str,
    phone_number: str,
    profile,
    memory: MemoryStore,
):
    """
    Build the full real-time voice pipeline for a B2C call.
    """
    # Per-call, not a shared global: with multiple simultaneous callers (point 1
    # from day one), a single module-level tracker would mix metrics across
    # calls, and one call finishing would reset another call's in-progress data.
    tracker = LatencyTracker()

    # VAD analyzer wired into transport for barge-in / natural turn-taking (ADR-003)
    vad_analyzer = SileroVADAnalyzer()

    serializer = ExotelFrameSerializer(stream_sid=stream_sid, call_sid=call_sid)

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            serializer=serializer,
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=vad_analyzer,  # Enables VAD analysis, User*SpeakingFrame emission, and interruption path
        ),
    )

    aiohttp_session = aiohttp.ClientSession()

    # STT: saaras:v3 is required for mode=codemix (saarika:v2.5 rejects mode).
    stt_language = profile.language or "hi-IN"
    stt = SarvamSTTService(
        api_key=SARVAM_API_KEY,
        mode="codemix",
        settings=SarvamSTTService.Settings(
            model="saaras:v3",
            language=stt_language,
        ),
    )

    # TTS - use user's chosen voice (Settings pattern; field is `voice`, not voice_id)
    voice_id = profile.voice_id or DEFAULT_VOICE
    tts = SarvamHttpTTSService(
        api_key=SARVAM_API_KEY,
        aiohttp_session=aiohttp_session,
        settings=SarvamHttpTTSSettings(
            voice=voice_id,
            model="bulbul:v2",
        ),
    )

    # LLM: full Sarvam stack (STT + LLM + TTS). Default sarvam-30b for lower latency.
    # Sarvam defaults reasoning_effort to "medium" unless explicitly null — that
    # burns tokens on hidden reasoning and can leave content empty on short
    # max_tokens. Force null for natural phone turn latency.
    llm = SarvamLLMService(
        api_key=SARVAM_API_KEY,
        base_url=SARVAM_LLM_BASE_URL,
        settings=SarvamLLMService.Settings(
            model=SARVAM_LLM_MODEL,
            max_tokens=256,
            temperature=0.3,
            extra={"reasoning_effort": None},
        ),
    )

    # Safety Guardrails (runs in parallel)
    # Shared state for crisis/medical priority protection (barge-in must not cancel)
    safety_runtime_state = {}
    safety = SafetyGuardrailProcessor(runtime_state=safety_runtime_state)

    # Per-call instrumentation processors (ADR-003 + ADR-004 measurement events)
    # Emits privacy-first events for latency, barge-in. No PII.
    # Safety priority: uses shared safety_runtime_state["priority_active"] so that
    # crisis / medical / high-severity UninterruptibleTTSSpeakFrame cannot be cancelled by barge-in.
    class _LatencyInstrumentationProcessor(FrameProcessor):
        def __init__(self, tracker: LatencyTracker, name: str = "", **kwargs):
            super().__init__(**kwargs)
            self.tracker = tracker
            self.name = name
            self._first_tts_audio = False

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)

            if isinstance(frame, UserStoppedSpeakingFrame):
                self.tracker.mark_user_finished()
                print(f"[MEASUREMENT] event=user_finished source=vad_end processor={self.name} timestamp={time.time():.3f}")
                self._first_tts_audio = False
            elif isinstance(frame, TranscriptionFrame) and frame.finalized and frame.text.strip():
                self.tracker.mark_user_finished()
                print(f"[MEASUREMENT] event=user_finished source=final_stt processor={self.name} timestamp={time.time():.3f}")
            elif isinstance(frame, TTSAudioRawFrame) and not self._first_tts_audio:
                self.tracker.mark_agent_started()
                print(f"[MEASUREMENT] event=agent_started source=first_tts_audio processor={self.name} timestamp={time.time():.3f}")
                self._first_tts_audio = True
            elif isinstance(frame, InterruptionFrame):
                print(f"[MEASUREMENT] event=barge_in_detected processor={self.name} timestamp={time.time():.3f}")
                # Protect crisis / medical / high-severity safety redirects from barge-in
                if safety_runtime_state.get("priority_active"):
                    print(f"[SAFETY] Priority redirect active ({safety_runtime_state.get('priority_reason')}) – suppressing barge-in cancel")
                    return  # Do not forward InterruptionFrame → TTS continues

            await self.push_frame(frame, direction)

    input_measurement = _LatencyInstrumentationProcessor(tracker, name="input")
    stt_measurement = _LatencyInstrumentationProcessor(tracker, name="stt")
    tts_measurement = _LatencyInstrumentationProcessor(tracker, name="tts")

    # Load system prompt from memory cache (avoids blocking disk I/O per call)
    system_prompt_template = get_prompt("system_prompt.txt")
    if system_prompt_template:
        system_prompt = system_prompt_template.replace("{context_blob}", profile.to_context_blob())
    else:
        system_prompt = f"You are a helpful phone assistant. {profile.to_context_blob()}"

    context = LLMContext(messages=[{"role": "system", "content": system_prompt}])
    context_aggregator = LLMContextAggregatorPair(context)

    # Build pipeline with VAD-enabled transport + instrumentation at key points
    pipeline = Pipeline([
        transport.input(),
        input_measurement,      # VAD end + barge-in detection
        stt,
        stt_measurement,        # final STT for user_finished
        safety,
        context_aggregator.user(),
        llm,
        tts,
        tts_measurement,        # first TTS audio for agent_started
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=EXOTEL_SAMPLE_RATE,
            audio_out_sample_rate=EXOTEL_SAMPLE_RATE,
        ),
    )

    runner = PipelineRunner()
    await runner.run(task)

    await aiohttp_session.close()

    # After call ends
    summary = tracker.get_summary()
    print(f"[METRICS] Call ended for {phone_number}")
    print(f"[METRICS] Summary: {summary}")

    # Update persistent memory -- entirely off the live call's latency budget.
    full_transcript = "\n".join(
        f"{m.get('role')}: {m.get('content')}"
        for m in context.get_messages()
        if m.get("role") != "system"
    )
    if full_transcript.strip():
        # Same Sarvam OpenAI-compatible endpoint for post-call summarization.
        summarizer_client = AsyncOpenAI(
            api_key=SARVAM_API_KEY,
            base_url=SARVAM_LLM_BASE_URL,
            default_headers={"api-subscription-key": SARVAM_API_KEY} if SARVAM_API_KEY else None,
        )

        async def _summarize_with_fast_model(prompt: str) -> str:
            response = await summarizer_client.chat.completions.create(
                model=SARVAM_LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "Return valid JSON only. No markdown fences.",
                    },
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
        print(f"[MEMORY] Updated summary for {phone_number}: {new_summary[:80]}...")
