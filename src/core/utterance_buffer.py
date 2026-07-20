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

# When the model echoes its own previous reply, the caller has almost always
# been cut off mid-thought -- so the right recovery is to invite them to
# continue, not to say the same thing again. Rotated so the recovery itself
# never becomes the new repetition.
_CONTINUE_PHRASES = {
    "te-IN": ["చెప్పండి, వింటున్నాను.", "అలాగా, ఆ తర్వాత?", "సరే, కొనసాగించండి."],
    "hi-IN": ["Haan, boliye — sun raha hoon.", "Achha, phir kya hua?", "Ji, bataiye."],
    "en-IN": ["Go on, I'm listening.", "Okay, and then?", "Sure, tell me more."],
}


def _normalize(text: str) -> str:
    """Loose key for duplicate detection: case/space/punctuation insensitive."""
    return re.sub(r"[^\w]+", "", (text or "").lower())

# Minimum characters before the early first chunk is worth sending on its own.
# Below this the network gap before the next chunk dominates and the reply
# sounds broken rather than responsive.
_MIN_FIRST_CHUNK_CHARS = 25


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

    def __init__(self, max_sentences: int = 3, language_getter=None):
        super().__init__()
        # Callable returning the active language code, for recovery phrasing.
        self._language_getter = language_getter
        self._last_first_chunk = ""
        self._suppress_rest = False
        self._continue_idx = 0
        self._parts: list[str] = []
        self._in_response = False
        self._sent_count = 0
        self._max_sentences = max_sentences
        # Release the FIRST sentence early, then batch the rest into one chunk.
        #
        # SarvamHttpTTSService issues a separate HTTP request per text frame, so
        # emitting every sentence separately put a real network gap between them
        # -- measured 317-729ms of silence mid-reply on a live call, which the
        # caller heard as the voice "breaking". One early chunk plus one batched
        # chunk keeps fast time-to-first-audio with at most a single seam.
        self._first_released = False

    def _reset(self):
        self._parts = []
        self._sent_count = 0
        self._first_released = False
        self._suppress_rest = False

    def _continue_phrase(self) -> str:
        lang = "hi-IN"
        if self._language_getter:
            try:
                lang = self._language_getter() or "hi-IN"
            except Exception:
                pass
        options = _CONTINUE_PHRASES.get(lang, _CONTINUE_PHRASES["hi-IN"])
        phrase = options[self._continue_idx % len(options)]
        self._continue_idx += 1
        return phrase

    def _pending(self) -> str:
        """Collapse whitespace runs but PRESERVE a trailing space.

        Stripping the tail here glues the next token onto the current
        remainder ("B." + "C. " -> "B.C."), which TTS then reads as one
        run-together word. Only the leading side is safe to strip.
        """
        return re.sub(r"\s+", " ", "".join(self._parts)).lstrip()

    async def _guard_repeat(self, opening: str, direction: FrameDirection) -> bool:
        """If this reply opens exactly like the last one, speak a nudge instead.

        Observed on a live call: with the correct history in context (including
        its own previous reply and the caller's new message), the model still
        regenerated its previous turn verbatim -- twice. frequency/presence
        penalties did not prevent it. The trigger was a cut-off caller
        utterance, so inviting them to continue is the right recovery.

        Returns True if the reply was replaced.
        """
        key = _normalize(opening)
        if key and key == self._last_first_chunk:
            phrase = self._continue_phrase()
            logger.warning(
                f"FullUtteranceBuffer: model repeated its previous reply "
                f"({opening[:60]!r}) -> substituting {phrase!r}"
            )
            self._suppress_rest = True
            self._parts = []
            self._sent_count += 1
            await self.push_frame(LLMTextFrame(text=phrase + " "), direction)
            return True
        self._last_first_chunk = key
        return False

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

            # Release ONLY the first sentence early, so TTS starts speaking
            # while the LLM is still generating. Everything after it is held
            # and flushed as a single chunk at end of response.
            if not self._first_released:
                pending = self._pending()
                match = _SENTENCE_END.search(pending)
                # Don't release a tiny fragment like "Namaste!" on its own --
                # the seam then lands immediately and sounds like a stutter.
                # Wait until the early chunk carries real content.
                if match and match.end() >= _MIN_FIRST_CHUNK_CHARS:
                    sentence, remainder = pending[: match.end()], pending[match.end() :]
                    self._parts = [remainder]
                    self._first_released = True
                    if await self._guard_repeat(sentence, direction):
                        return
                    await self._emit(sentence, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            self._in_response = False
            tail = self._pending()
            if tail and not self._suppress_rest:
                if not self._first_released and await self._guard_repeat(tail, direction):
                    self._parts = []
                    await self.push_frame(frame, direction)
                    return
                # Flush the remainder as ONE chunk (cap total sentences spoken).
                parts = _SENTENCE_END.split(tail)
                allowed = max(0, self._max_sentences - self._sent_count)
                if allowed:
                    await self._emit(" ".join(parts[:allowed]), direction)
            self._parts = []
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
