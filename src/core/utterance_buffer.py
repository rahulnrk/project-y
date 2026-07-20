"""
Buffer streaming LLM text into ONE spoken utterance per bot turn,
and lightly polish text so TTS sounds more fluid (ChatGPT-Voice-like).
"""

import re

from loguru import logger

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def polish_for_speech(text: str) -> str:
    """Make model text more TTS-friendly and human on a phone line."""
    if not text:
        return text

    t = text.strip()
    # Drop markdown / list chrome that sounds robotic when spoken
    t = re.sub(r"[*_`#]+", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t)

    # Soften stiff openers that create IVR feel
    stiff = [
        (r"^(Sure!?|Okay!?|Got it!?|Great!?|Absolutely!?)\s*", ""),
        (r"^(Theek hai!|Zaroor!|Bilkul!)\s*[!.]?\s*", r"\1, "),
    ]
    for pat, rep in stiff:
        t = re.sub(pat, rep, t, count=1, flags=re.I)

    # Prefer spoken connectors over hard multi-sentence chop for short replies
    # Keep at most ~3 sentences worth of content for phone fluidity
    parts = re.split(r"(?<=[\.!\?।])\s+", t)
    if len(parts) > 3:
        t = " ".join(parts[:3])

    # Gentle trailing calm (helps TTS end cleanly)
    t = t.strip()
    if t and t[-1] not in ".!?।…":
        t += "."

    return t


class FullUtteranceBuffer(FrameProcessor):
    """Hold LLM tokens until the response ends, then emit one polished TextFrame."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._in_response = False

    def _flush_text(self) -> str:
        text = "".join(self._parts)
        text = " ".join(text.split())
        self._parts = []
        return polish_for_speech(text)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            self._parts = []
            self._in_response = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._parts = []
            self._in_response = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (LLMTextFrame, TextFrame)) and self._in_response:
            piece = getattr(frame, "text", "") or ""
            if piece:
                self._parts.append(piece)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            full = self._flush_text()
            self._in_response = False
            if full:
                logger.debug(
                    f"FullUtteranceBuffer → speech ({len(full)} chars): {full[:140]!r}"
                )
                await self.push_frame(LLMTextFrame(text=full + " "), direction)
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
