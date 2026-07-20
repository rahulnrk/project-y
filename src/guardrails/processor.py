"""
processor.py - Pipecat FrameProcessor for safety guardrails
Runs in parallel (non-blocking) after STT
Uses soft empathetic redirects as requested
"""

import asyncio
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from .rules import (
    is_emergency,
    is_abusive,
    contains_sexual_content,
    contains_harm_content,
    get_soft_redirect,
)


class SafetyGuardrailProcessor(FrameProcessor):
    """
    Safety processor that observes transcripts and reacts with soft redirects.
    Never blocks the main pipeline in the happy path.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # NOTE: do NOT gate on frame.finalized. Sarvam's STT constructs
        # TranscriptionFrame without ever passing finalized=True (see
        # pipecat/services/sarvam/stt.py), so it always defaults to False and
        # this branch never ran -- safety was silently dead on every call.
        # Sarvam only emits a TranscriptionFrame on a final "data" message,
        # so every frame reaching here is already an utterance-final result.
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            text = frame.text.strip()

            # Run safety checks concurrently (non-blocking)
            asyncio.create_task(self._check_and_redirect(text))

        # Always forward the frame immediately
        await self.push_frame(frame, direction)

    async def _check_and_redirect(self, text: str):
        """Run safety classification and react if needed"""

        # 1. Crisis / Self-harm → Strong but warm redirect
        if is_emergency(text):
            await self.push_frame(
                TTSSpeakFrame(text=get_soft_redirect("crisis")),
                FrameDirection.DOWNSTREAM
            )
            return

        # 2. Sexual / Romantic content
        if contains_sexual_content(text):
            await self.push_frame(
                TTSSpeakFrame(text=get_soft_redirect("sexual")),
                FrameDirection.DOWNSTREAM
            )
            return

        # 3. Harm to people or animals
        if contains_harm_content(text):
            await self.push_frame(
                TTSSpeakFrame(text=get_soft_redirect("harm")),
                FrameDirection.DOWNSTREAM
            )
            return

        # 4. Abuse / Harassment
        if is_abusive(text):
            await self.push_frame(
                TTSSpeakFrame(text=get_soft_redirect("abuse")),
                FrameDirection.DOWNSTREAM
            )
            return

        # No unsafe content detected → do nothing (happy path)