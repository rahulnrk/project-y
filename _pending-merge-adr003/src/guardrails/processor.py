"""
processor.py – Pipecat FrameProcessor for safety guardrails

- Parallel / non-blocking on happy path and medium severity
- High-severity: do NOT forward TranscriptionFrame (suppresses LLM)
- High-severity: push protected TTSSpeakFrame that should not be cancelled by barge-in
"""

import asyncio
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from .rules import classify_safety, SafetyResult


class UninterruptibleTTSSpeakFrame(TTSSpeakFrame):
    """
    TTSSpeakFrame that the Voice Pipeline / interruption logic must treat
    as non-cancellable (crisis, medical, high-severity sexual/harm).

    Pipecat 1.5+ style: prefer mixin if available; this attribute-based
    marker is the practical equivalent for current coordination.
    """
    def __init__(self, text: str, **kwargs):
        super().__init__(text=text, **kwargs)
        self.interruptible = False
        self.priority = True
        self.safety_protected = True


class SafetyGuardrailProcessor(FrameProcessor):
    """
    Observes finalized transcripts.

    High-severity → do not forward text to LLM + speak protected redirect.
    Medium → forward text + async soft redirect (parallel).
    """

    def __init__(self, runtime_state: dict | None = None, **kwargs):
        super().__init__(**kwargs)
        # Shared mutable state with Voice Pipeline for interruption protection.
        self.runtime_state = runtime_state if runtime_state is not None else {}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Do NOT gate on frame.finalized -- Sarvam STT never sets it (always
        # False), which would make every rule below dead code. Sarvam emits a
        # TranscriptionFrame only on a final "data" message.
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            text = frame.text.strip()
            result = classify_safety(text)

            if result is None:
                # Happy path – forward immediately, zero extra latency
                await self.push_frame(frame, direction)
                return

            if result.should_suppress_llm:
                # HIGH SEVERITY
                # 1. Do NOT push the TranscriptionFrame → LLM never sees the text
                # 2. Speak protected redirect that barge-in must not cancel
                self.runtime_state["priority_active"] = True
                self.runtime_state["priority_reason"] = result.category
                self.runtime_state["priority_helpline"] = result.helpline

                await self.push_frame(
                    UninterruptibleTTSSpeakFrame(text=result.redirect_text),
                    FrameDirection.DOWNSTREAM,
                )

                # Clear the flag after the redirect has time to finish
                asyncio.create_task(self._clear_priority_after_delay())
                return

            # MEDIUM SEVERITY – keep parallel behaviour
            await self.push_frame(frame, direction)
            asyncio.create_task(self._soft_redirect(result))
            return

        # All other frames forward normally
        await self.push_frame(frame, direction)

    async def _soft_redirect(self, result: SafetyResult):
        """Medium-severity async soft redirect (non-blocking)."""
        await self.push_frame(
            TTSSpeakFrame(text=result.redirect_text),
            FrameDirection.DOWNSTREAM,
        )

    async def _clear_priority_after_delay(self, delay: float = 14.0):
        """Clear priority flag after the redirect has had time to finish."""
        await asyncio.sleep(delay)
        self.runtime_state["priority_active"] = False
        self.runtime_state.pop("priority_reason", None)
        self.runtime_state.pop("priority_helpline", None)
