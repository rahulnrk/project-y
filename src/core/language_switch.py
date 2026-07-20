"""
Explicit mid-call language switch (Telugu / Hindi / English).
Updates TTS+STT language and rewrites context cleanly (no sticky system spam).
"""

import re
from typing import Optional

from loguru import logger

from pipecat.frames.frames import (
    Frame,
    STTUpdateSettingsFrame,
    TranscriptionFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Explicit switch only — do not fire on random Telugu speech content.
_LANG_PATTERNS = [
    (
        "te-IN",
        re.compile(
            r"(?:\btelugu\b|\bతెలుగు\b).{0,20}(?:\bplease\b|\blo\b|\bmein\b|\bme\b|\bmatlad|\bspeak\b|\bbat|\bbaat)?"
            r"|^(?:telugu|తెలుగు)(?:\s+please)?$"
            r"|(?:speak|talk|baat|bat).{0,12}(?:telugu|తెలుగు)",
            re.I,
        ),
    ),
    (
        "hi-IN",
        re.compile(
            r"(?:\bhindi\b|\bहिंदी\b|\bहिन्दी\b).{0,20}(?:\bplease\b|\bmein\b|\bme\b|\bspeak\b|\bbat)?"
            r"|^(?:hindi|हिंदी|हिन्दी)(?:\s+please)?$"
            r"|(?:speak|talk|baat).{0,12}(?:hindi|हिंदी)",
            re.I,
        ),
    ),
    (
        "en-IN",
        re.compile(
            r"(?:\benglish\b|\bangrezi\b|\bअंग्रेजी\b).{0,20}(?:\bplease\b|\bspeak\b)?"
            r"|^(?:english|angrezi)(?:\s+please)?$"
            r"|(?:speak|talk|in)\s+english",
            re.I,
        ),
    ),
]

_LABELS = {
    "hi-IN": "Hindi (not Marathi)",
    "te-IN": "Telugu",
    "en-IN": "English",
}

# The one-shot greeting cue pipeline.py injects on connect. It is a *user*
# message, so it must be scrubbed by role="user" handling below -- and both
# pipeline.py and this module must agree on the exact string. Previously the
# cue read "(Call connected." while the scrub list said "(Call just connected",
# so it never matched: the cue survived every turn and the model kept re-reading
# "ask my name casually" as something the caller had just said. That is what
# produced the mid-call repetition and re-introductions.
CALL_CUE_PREFIX = "(Call connected."

_EPHEMERAL_PREFIXES = (
    "LANGUAGE SWITCH:",
    "ONE short",
    "REAL TIME NOW",
    CALL_CUE_PREFIX,
)

# Always dropped on the next turn regardless of length (search results can
# exceed the 400-char "looks like a base prompt" guard below).
_ALWAYS_EPHEMERAL_PREFIXES = ("LIVE SEARCH RESULTS",)


def detect_language_request(text: str) -> Optional[str]:
    if not text:
        return None
    for code, pattern in _LANG_PATTERNS:
        if pattern.search(text.strip()):
            return code
    return None


def _scrub_ephemeral(messages: list) -> list:
    """Drop one-shot injects so they never accumulate in context.

    Handles both roles: short system injects (language-switch notes, time
    blobs) and the user-role greeting cue. Only the long base system prompt
    is preserved.
    """
    cleaned = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""

        # User-role greeting cue: always ephemeral, drop on sight.
        if role == "user" and content.startswith(CALL_CUE_PREFIX):
            continue

        if role != "system":
            cleaned.append(m)
            continue

        if any(content.startswith(p) for p in _ALWAYS_EPHEMERAL_PREFIXES):
            continue

        if any(content.startswith(p) or p in content[:40] for p in _EPHEMERAL_PREFIXES):
            # Keep the main base system prompt (long); drop short injects
            if len(content) < 400:
                continue
        cleaned.append(m)
    return cleaned


def _trim_history(messages: list, max_turns: int = 8) -> list:
    """Keep base system + last N user/assistant messages."""
    systems = [m for m in messages if m.get("role") == "system"]
    base = systems[:1] if systems else []
    dialogue = [m for m in messages if m.get("role") in ("user", "assistant")]
    # Drop leading orphan user spam if more than max_turns*2
    dialogue = dialogue[-(max_turns * 2) :]
    # Collapse consecutive same-role user messages into one (bad STT stacking)
    collapsed = []
    for m in dialogue:
        if (
            collapsed
            and collapsed[-1].get("role") == "user"
            and m.get("role") == "user"
        ):
            prev = (collapsed[-1].get("content") or "").strip()
            cur = (m.get("content") or "").strip()
            # Blind concatenation produced garbled duplicates in a live call
            # ("Like your voice is loud enough Your voice is loud enough but")
            # when STT re-sent an overlapping partial. Keep the longer one when
            # either contains the other; only join genuinely distinct text.
            if not prev:
                merged = cur
            elif not cur or cur in prev:
                merged = prev
            elif prev in cur:
                merged = cur
            else:
                merged = f"{prev} {cur}"
            collapsed[-1] = {"role": "user", "content": merged}
        else:
            collapsed.append(m)
    return base + collapsed


# Languages we actually support end-to-end. STT auto-detect will sometimes
# mis-tag Indic audio as Punjabi/Malayalam/Marathi; those must never trigger a
# switch, otherwise one bad frame drags the whole call into a language neither
# side wanted. Anything outside this set is ignored.
SUPPORTED_SWITCH_LANGS = ("hi-IN", "te-IN", "en-IN")

# Consecutive detections required before following the caller implicitly.
# An explicit request ("speak English") switches immediately; drifting on a
# single auto-detected frame is what caused earlier language thrash.
_IMPLICIT_SWITCH_THRESHOLD = 2

# Minimum utterance length before auto-detected language counts as intent.
_MIN_CHARS_FOR_IMPLICIT = 12


class LanguageSwitchProcessor(FrameProcessor):
    """Keeps STT, TTS, and the system prompt agreed on one active language.

    Two paths in:
      - explicit ("bolo English mein")     -> switch immediately
      - implicit (caller just speaks Telugu) -> switch after N consistent
        auto-detected frames

    The switch rewrites the *base* system prompt rather than appending a note.
    Appending was the bug: the note began "LANGUAGE SWITCH:" and was under 400
    chars, so _scrub_ephemeral deleted it on the very next turn and the base
    prompt -- which still pinned the original language -- took over again. That
    is why the bot said "yes, English" and then immediately reverted to Hindi.
    """

    def __init__(
        self,
        profile,
        context,
        tts_service=None,
        stt_service=None,
        system_prompt_builder=None,
    ):
        super().__init__()
        self._profile = profile
        self._context = context
        self._tts = tts_service
        self._stt = stt_service
        # Callable returning the full base system prompt for profile.language.
        self._build_system_prompt = system_prompt_builder
        self._current = profile.language or "hi-IN"
        self._pending_lang: str | None = None
        self._pending_count = 0
        self.call_log = None  # optional CallLog, set by pipeline.py

    def _rewrite_context(self, extra_system: str | None = None):
        msgs = _scrub_ephemeral(list(self._context.get_messages()))
        msgs = _trim_history(msgs, max_turns=8)
        if extra_system:
            msgs.append({"role": "system", "content": extra_system})
        self._context.set_messages(msgs)

    def _rebuild_base_prompt(self):
        """Replace the base system prompt so the new language persists."""
        if not self._build_system_prompt:
            return
        msgs = _scrub_ephemeral(list(self._context.get_messages()))
        msgs = _trim_history(msgs, max_turns=8)
        rebuilt = self._build_system_prompt()
        if msgs and msgs[0].get("role") == "system":
            msgs[0] = {"role": "system", "content": rebuilt}
        else:
            msgs.insert(0, {"role": "system", "content": rebuilt})
        self._context.set_messages(msgs)

    def _detected_code(self, frame) -> str | None:
        """Normalize TranscriptionFrame.language (a Language enum) to a code."""
        lang = getattr(frame, "language", None)
        if lang is None:
            return None
        code = getattr(lang, "value", None) or str(lang)
        return code if code in SUPPORTED_SWITCH_LANGS else None

    async def _apply_switch(self, target: str, direction: FrameDirection, why: str):
        self._current = target
        self._profile.language = target
        self._pending_lang = None
        self._pending_count = 0
        logger.info(f"Language switch → {target} ({why})")
        if self.call_log is not None:
            self.call_log.event("language_switch", to=target, why=why)

        # Persist the change in the base prompt, not an ephemeral note.
        self._rebuild_base_prompt()

        await self.push_frame(
            TTSUpdateSettingsFrame(settings={"language": target}, service=self._tts),
            direction,
        )
        if self._stt is not None:
            # Sarvam bakes language_code into the STT websocket connect, so this
            # triggers a reconnect internally (see sarvam/stt.py _update_settings).
            await self.push_frame(
                STTUpdateSettingsFrame(settings={"language": target}, service=self._stt),
                direction,
            )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            # Always scrub sticky injects + trim history before each user turn
            self._rewrite_context()

            # 1. Explicit request wins outright.
            requested = detect_language_request(frame.text)
            if requested and requested != self._current:
                await self._apply_switch(requested, direction, "explicit request")
                await self.push_frame(frame, direction)
                return

            # 2. Otherwise follow the language the caller is actually speaking.
            # Short utterances are unreliable language signals -- a live call
            # flipped to en-IN on "I'm Rahul" and back to hi-IN a turn later.
            # Require some substance before treating detection as intent.
            if not requested and len(frame.text.strip()) >= _MIN_CHARS_FOR_IMPLICIT:
                detected = self._detected_code(frame)
                if detected and detected != self._current:
                    if detected == self._pending_lang:
                        self._pending_count += 1
                    else:
                        self._pending_lang = detected
                        self._pending_count = 1
                    if self._pending_count >= _IMPLICIT_SWITCH_THRESHOLD:
                        await self._apply_switch(detected, direction, "caller's speech")
                elif detected == self._current:
                    self._pending_lang = None
                    self._pending_count = 0

        await self.push_frame(frame, direction)
