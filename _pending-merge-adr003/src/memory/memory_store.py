"""
memory_store.py - Redis-backed persistent memory per phone number
Designed for both B2C personal agents and B2B customer memory
"""

import json
import os
import time
from dataclasses import asdict, is_dataclass, fields
from datetime import datetime, date
from typing import Any, Optional

import redis.asyncio as redis

from ..config import REDIS_URL, PRODUCT, ALL_VOICES
from ..models.caller_profile import CallerProfile, Reminder, DailyGoal

KEY_PREFIX = "caller"


def normalize_phone(phone_number: str) -> str:
    """Normalize to last 10 digits (Indian mobile). Empty or non-numeric → 'unknown'."""
    if not phone_number or phone_number.lower() in ("unknown", "none", "null"):
        return "unknown"
    digits = "".join(ch for ch in str(phone_number) if ch.isdigit())
    if len(digits) >= 10:
        return digits[-10:]  # last 10 digits handles +91 / 0 prefix
    if digits:
        return digits
    return "unknown"


def _key(phone_number: str) -> str:
    """Stable Redis key. Unknown callers are isolated (never share one profile)."""
    norm = normalize_phone(phone_number)
    if norm == "unknown":
        # Isolation: do not allow a shared "caller::profile" key.
        # Callers that arrive as "unknown" get an ephemeral key; real numbers
        # are always last-10-digits so the same handset always maps together.
        return f"{KEY_PREFIX}:unknown:ephemeral"
    return f"{KEY_PREFIX}:{norm}:profile"


def _json_default(obj: Any) -> Any:
    """Make datetime/date JSON-serializable (ISO strings)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _profile_to_dict(profile: CallerProfile) -> dict:
    """asdict + datetime → ISO. Safe for json.dumps."""
    return asdict(profile)


def _profile_from_dict(data: dict) -> CallerProfile:
    """Rehydrate CallerProfile, restoring datetime fields from ISO strings."""
    # Reminder.created_at
    reminders = []
    for r in data.get("reminders") or []:
        if isinstance(r.get("created_at"), str):
            try:
                r["created_at"] = datetime.fromisoformat(r["created_at"])
            except ValueError:
                r["created_at"] = datetime.now()
        reminders.append(Reminder(**r) if not isinstance(r, Reminder) else r)
    data["reminders"] = reminders

    # DailyGoal.date is already a string by design; leave it.
    goals = []
    for g in data.get("daily_goals") or []:
        goals.append(DailyGoal(**g) if not isinstance(g, DailyGoal) else g)
    data["daily_goals"] = goals

    # consent_given_at
    cga = data.get("consent_given_at")
    if isinstance(cga, str):
        try:
            data["consent_given_at"] = datetime.fromisoformat(cga)
        except ValueError:
            data["consent_given_at"] = None

    # first_call_at / last_call_at are floats (unix) by design — leave them.
    return CallerProfile(**data)


def _make_redis_client(redis_url: str):
    """Real Redis by default; in-memory fakeredis for local dev without Docker.

    Enable with REDIS_URL=memory:// or USE_FAKE_REDIS=1
    """
    use_fake = (
        redis_url in (None, "", "memory://", "fakeredis://")
        or os.environ.get("USE_FAKE_REDIS", "").lower() in ("1", "true", "yes")
    )
    if use_fake:
        try:
            import fakeredis.aioredis

            print("[memory] Using in-memory fakeredis (local/dev mode)")
            return fakeredis.aioredis.FakeRedis(decode_responses=True)
        except ImportError as e:
            raise RuntimeError(
                "USE_FAKE_REDIS/memory:// requested but fakeredis is not installed. "
                "pip install fakeredis"
            ) from e
    return redis.from_url(redis_url, decode_responses=True)


class MemoryStore:
    def __init__(self, redis_url: str = REDIS_URL, max_recent_facts: int = None):
        self._redis = _make_redis_client(redis_url)
        self._max_recent_facts = max_recent_facts or PRODUCT.max_recent_facts

    async def close(self):
        await self._redis.aclose()

    async def get_profile(self, phone_number: str) -> CallerProfile:
        """Fetch full profile in one round-trip. Unknown numbers never share state."""
        norm = normalize_phone(phone_number)
        if norm == "unknown":
            # Isolation guarantee: never load or share a profile for unknown callers.
            return CallerProfile(phone_number="unknown")
        raw = await self._redis.get(_key(phone_number))
        if raw is None:
            return CallerProfile(phone_number=norm)
        data = json.loads(raw)
        return _profile_from_dict(data)

    async def save_profile(self, profile: CallerProfile) -> None:
        norm = normalize_phone(profile.phone_number)
        if norm == "unknown":
            # Do not persist unknown-caller state (prevents cross-caller leakage).
            return
        profile.phone_number = norm  # keep stored form clean
        payload = _profile_to_dict(profile)
        await self._redis.set(_key(norm), json.dumps(payload, default=_json_default))

    async def start_call(self, phone_number: str) -> CallerProfile:
        """Call at the beginning of every call. Normalizes and isolates unknowns."""
        profile = await self.get_profile(phone_number)
        now = time.time()

        if profile.first_call_at is None:
            profile.first_call_at = now
        profile.last_call_at = now
        profile.total_calls += 1

        await self.save_profile(profile)
        return profile

    async def append_call_summary(
        self, 
        phone_number: str, 
        new_facts: list[str], 
        updated_rolling_summary: str
    ) -> None:
        """Called after call ends (off critical path)"""
        profile = await self.get_profile(phone_number)
        profile.rolling_summary = updated_rolling_summary

        # Prepend new facts, keep only the most recent ones
        profile.recent_facts = (new_facts + profile.recent_facts)[:self._max_recent_facts]
        await self.save_profile(profile)

    async def delete_user_data(self, phone_number: str) -> bool:
        """Privacy: Complete data deletion ("Forget me")"""
        deleted = await self._redis.delete(_key(phone_number))
        return deleted > 0

    async def update_voice_preference(self, phone_number: str, voice_id: str) -> None:
        profile = await self.get_profile(phone_number)
        if voice_id in ALL_VOICES:  # from config
            profile.voice_id = voice_id
            await self.save_profile(profile)


async def summarize_call(llm_summarize_fn, transcript: str, previous_summary: str):
    """Fire-and-forget after a call ends -- entirely off the live call's latency
    budget. llm_summarize_fn: async callable(prompt: str) -> str, your fast/cheap
    model call. Returns (updated_rolling_summary: str, new_facts: list[str]).
    Nothing was calling this + MemoryStore.append_call_summary together yet --
    see pipeline.py for the wiring."""
    prompt = (
        "You maintain a short rolling memory of a phone caller across many calls.\n"
        f"Previous summary: {previous_summary or '(none yet)'}\n\n"
        f"Transcript of the call that just ended:\n{transcript}\n\n"
        "Return JSON only, with two fields:\n"
        '  "summary": an updated 2-4 sentence rolling summary (rewrite fully, '
        "don't just append)\n"
        '  "facts": up to 3 short, specific new facts worth remembering next time '
        "-- empty list if nothing new stands out"
    )
    raw = await llm_summarize_fn(prompt)
    try:
        data = json.loads(raw)
        return data.get("summary", previous_summary), data.get("facts", [])
    except (json.JSONDecodeError, TypeError):
        # A malformed summarizer response should never wipe out existing memory.
        return previous_summary, []