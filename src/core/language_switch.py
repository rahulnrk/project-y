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

_EPHEMERAL_PREFIXES = (
    "LANGUAGE SWITCH:",
    "ONE short",
    "REAL TIME NOW",
    "(Call just connected",
)


def detect_language_request(text: str) -> Optional[str]:
    if not text:
        return None
    for code, pattern in _LANG_PATTERNS:
        if pattern.search(text.strip()):
            return code
    return None


def _scrub_ephemeral_system(messages: list) -> list:
    cleaned = []
    for m in messages:
        if m.get("role") != "system":
            cleaned.append(m)
            continue
        content = m.get("content") or ""
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
            collapsed[-1] = {
                "role": "user",
                "content": (collapsed[-1].get("content") or "") + " " + (m.get("content") or ""),
            }
        else:
            collapsed.append(m)
    return base + collapsed


class LanguageSwitchProcessor(FrameProcessor):
    def __init__(self, profile, context, tts_service=None, stt_service=None):
        super().__init__()
        self._profile = profile
        self._context = context
        self._tts = tts_service
        self._stt = stt_service
        self._current = profile.language or "hi-IN"

    def _rewrite_context(self, extra_system: str | None = None):
        msgs = _scrub_ephemeral_system(list(self._context.get_messages()))
        msgs = _trim_history(msgs, max_turns=8)
        if extra_system:
            msgs.append({"role": "system", "content": extra_system})
        self._context.set_messages(msgs)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text:
            # Always scrub sticky injects + trim history before each user turn
            self._rewrite_context()

            requested = detect_language_request(frame.text)
            if requested and requested != self._current:
                self._current = requested
                self._profile.language = requested
                label = _LABELS[requested]
                logger.info(f"Language switch → {requested}")
                self._rewrite_context(
                    extra_system=(
                        f"LANGUAGE SWITCH: Speak ONLY {label} from now on. "
                        f"Acknowledge in one short phrase in {label}. "
                        f"Do not re-introduce yourself. Answer their next message on-topic."
                    )
                )
                await self.push_frame(
                    TTSUpdateSettingsFrame(
                        settings={"language": requested},
                        service=self._tts,
                    ),
                    direction,
                )
                if self._stt is not None:
                    await self.push_frame(
                        STTUpdateSettingsFrame(
                            settings={"language": requested},
                            service=self._stt,
                        ),
                        direction,
                    )

        await self.push_frame(frame, direction)
