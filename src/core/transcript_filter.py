"""
Drop empty / noise STT results so they never enter LLM context.
"""

import re

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Pure punctuation / filler that should not trigger a model turn
_NOISE = re.compile(
    r"^[\s\.\,\!\?\;\:\-\…\|\/\\\'\"\`\~]+$"
    r"|^[अआएओउइ]+$"
    r"|^(uh+|um+|aa+|haan+|ha+|ok|okay|hmm+)$",
    re.I,
)

# Scripts we can actually converse in: Devanagari (Hindi), Telugu, Latin.
# On noisy 8kHz telephone audio, Sarvam auto-detect sometimes mis-tags an
# utterance into another Indic language entirely -- a real call transcribed
# "Kompally" as Bengali "কম পারলেন?". Letting that reach the LLM produces a
# hallucinated reply in the wrong direction. Detect it and substitute a
# marker the system prompt knows: warmly ask the caller to repeat.
_KNOWN_SCRIPT = re.compile(r"[A-Za-z0-9ऀ-ॿఀ-౿]")
_FOREIGN_SCRIPT = re.compile(
    r"[ঀ-৿਀-੿઀-૿଀-୿"  # Bengali, Gurmukhi, Gujarati, Odia
    r"஀-௿ಀ-೿ഀ-ൿ]"               # Tamil, Kannada, Malayalam
)

GARBLED_MARKER = (
    "(The caller's audio was unclear or half-heard due to network noise. "
    "Warmly ask them to say it once more. Do not guess what they said.)"
)


def _looks_garbled(text: str) -> bool:
    foreign = len(_FOREIGN_SCRIPT.findall(text))
    known = len(_KNOWN_SCRIPT.findall(text))
    return foreign > 0 and foreign >= known


class TranscriptFilter(FrameProcessor):
    def __init__(self, min_chars: int = 2):
        super().__init__()
        self._min_chars = min_chars

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if not text or len(text) < self._min_chars or _NOISE.match(text):
                logger.debug(f"TranscriptFilter dropped: {text!r}")
                return  # swallow — do not push to LLM
            if _looks_garbled(text):
                logger.info(f"TranscriptFilter garbled -> recovery: {text!r}")
                frame.text = GARBLED_MARKER

        await self.push_frame(frame, direction)
