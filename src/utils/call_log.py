"""
call_log.py - Per-call JSONL event log + pipeline tap processors.

Every call writes logs/calls/<timestamp>_<call_sid>.jsonl with one JSON event
per line: user turns (with detected language), bot turns, language switches,
safety triggers, and end-of-call metrics. The /dashboard routes in server.py
render these files. Transcripts stay on this machine only.
"""

import json
import os
import time
from datetime import datetime

from loguru import logger

from pipecat.frames.frames import Frame, LLMTextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

LOG_DIR = os.path.join("logs", "calls")


class CallLog:
    """Append-only JSONL event log for one call."""

    def __init__(self, call_sid: str, phone_number: str):
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_sid = "".join(c for c in (call_sid or "nosid") if c.isalnum() or c in "-_")[:40]
        self.path = os.path.join(LOG_DIR, f"{stamp}_{safe_sid}.jsonl")
        self._t0 = time.time()
        self.event("call_started", phone=phone_number, call_sid=call_sid)

    def event(self, etype: str, **data):
        try:
            row = {"t": round(time.time() - self._t0, 2), "type": etype, **data}
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:  # logging must never break the call
            logger.warning(f"CallLog write failed: {e}")


class UserTurnTap(FrameProcessor):
    """Logs finalized user transcripts (with STT-detected language)."""

    def __init__(self, call_log: CallLog):
        super().__init__()
        self._log = call_log

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.text:
            lang = getattr(frame, "language", None)
            self._log.event(
                "user",
                text=frame.text,
                lang=getattr(lang, "value", None) or (str(lang) if lang else None),
            )
        await self.push_frame(frame, direction)


class BotTurnTap(FrameProcessor):
    """Logs bot speech chunks (placed after the utterance buffer)."""

    def __init__(self, call_log: CallLog):
        super().__init__()
        self._log = call_log

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame) and frame.text.strip():
            self._log.event("bot", text=frame.text.strip())
        await self.push_frame(frame, direction)
