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

        await self.push_frame(frame, direction)
