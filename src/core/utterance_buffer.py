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


def polish_for_speech(text: str, is_first: bool = True) -> str:
    """Make model text more TTS-friendly and human on a phone line.

    is_first: only the opening chunk of a turn gets its stiff opener softened.
    Now that text is emitted sentence-by-sentence, applying the ^-anchored
    rules to every chunk would strip legitimate mid-reply words like "Great".
    """
    if not text:
        return text

    t = text.strip()
    # Drop markdown / list chrome that sounds robotic when spoken
    t = re.sub(r"[*_`#]+", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t)

    # Soften stiff openers that create IVR feel
    if is_first:
        stiff = [
            (r"^(Sure!?|Okay!?|Got it!?|Great!?|Absolutely!?)\s*", ""),
            (r"^(Theek hai!|Zaroor!|Bilkul!)\s*[!.]?\s*", r"\1, "),
        ]
        for pat, rep in stiff:
            t = re.sub(pat, rep, t, count=1, flags=re.I)

    # Gentle trailing calm (helps TTS end cleanly)
    t = t.strip()
    if t and t[-1] not in ".!?।…":
        t += "."

    return t


_SENTENCE_END = re.compile(r"(?<=[\.!\?।…])\s")


class FullUtteranceBuffer(FrameProcessor):
    """Emit the first complete sentence early, then stream the remainder.

    The original version held *every* token until LLMFullResponseEndFrame, so
    time-to-first-audio equalled the full LLM completion -- long dead air, then
    a monologue. That is the main reason the call did not feel alive.

    Now we buffer only until the first sentence boundary and release it
    immediately, so TTS starts while the model is still generating. Later
    sentences are polished and forwarded as they complete. Total spoken content
    is unchanged; only the timing of the first audio frame moves.
    """

    def __init__(self, max_sentences: int = 3):
        super().__init__()
        self._parts: list[str] = []
        self._in_response = False
        self._sent_count = 0
        self._max_sentences = max_sentences

    def _reset(self):
        self._parts = []
        self._sent_count = 0

    def _pending(self) -> str:
        """Collapse whitespace runs but PRESERVE a trailing space.

        Stripping the tail here glues the next token onto the current
        remainder ("B." + "C. " -> "B.C."), which TTS then reads as one
        run-together word. Only the leading side is safe to strip.
        """
        return re.sub(r"\s+", " ", "".join(self._parts)).lstrip()

    async def _emit(self, text: str, direction: FrameDirection):
        """Polish one chunk and push it downstream to TTS."""
        polished = polish_for_speech(text, is_first=(self._sent_count == 0))
        if not polished:
            return
        self._sent_count += 1
        logger.debug(
            f"FullUtteranceBuffer → speech #{self._sent_count} "
            f"({len(polished)} chars): {polished[:100]!r}"
        )
        await self.push_frame(LLMTextFrame(text=polished + " "), direction)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            # Caller barged in: drop anything not yet spoken so we do not
            # resume a stale monologue after the interruption.
            self._reset()
            self._in_response = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._reset()
            self._in_response = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (LLMTextFrame, TextFrame)) and self._in_response:
            piece = getattr(frame, "text", "") or ""
            if piece:
                self._parts.append(piece)

            # Release each complete sentence as soon as it lands, so TTS can
            # start speaking while the LLM is still generating.
            while self._sent_count < self._max_sentences:
                pending = self._pending()
                match = _SENTENCE_END.search(pending)
                if not match:
                    break
                sentence, remainder = pending[: match.end()], pending[match.end() :]
                self._parts = [remainder]
                await self._emit(sentence, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            self._in_response = False
            # Trailing text with no terminal punctuation, or a reply short
            # enough that no boundary was ever hit.
            if self._sent_count < self._max_sentences:
                tail = self._pending()
                if tail:
                    await self._emit(tail, direction)
            self._parts = []
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
