"""
caller_profile.py - Data model for per-phone-number memory
Works for both B2C (personal) and B2B (customer) use cases
"""

from dataclasses import dataclass, field
from typing import Optional, Literal, List
from datetime import datetime, date


@dataclass
class Reminder:
    """Simple reminder structure for time-based reminders"""
    text: str
    time: str = ""                    # e.g. "21:00", "morning", "night"
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DailyGoal:
    """Simple daily goal structure"""
    text: str
    status: str = "pending"           # pending | done | skipped
    date: str = field(default_factory=lambda: date.today().isoformat())


@dataclass
class CallerProfile:
    phone_number: str
    name: Optional[str] = None
    age: Optional[int] = None                    # Self-reported only - never used for safety gating
    gender: Optional[Literal["male", "female", "other", "prefer_not_to_say"]] = None
    language: str = "hi-IN"                      # Preferred language
    voice_id: str = "anushka"                    # Chosen TTS voice
    voice_gender_pref: Optional[Literal["male", "female"]] = None
    personality: str = "friendly"                # friendly | professional | supportive | playful

    # Metadata
    # NOTE: memory_store.py sets these via time.time() (Unix timestamp floats),
    # not datetime objects -- typed to match actual runtime behavior. If you
    # want real datetimes, store them as ISO strings (JSON-safe) and parse on read.
    first_call_at: Optional[float] = None
    last_call_at: Optional[float] = None
    total_calls: int = 0
    total_minutes: float = 0.0

    # Memory
    rolling_summary: str = ""                    # 2-4 sentence running summary
    recent_facts: list[str] = field(default_factory=list)  # Most recent first, capped

    # Sticky Features - Structured
    daily_goals: List[DailyGoal] = field(default_factory=list)
    reminders: List[Reminder] = field(default_factory=list)
    last_evening_reflection: str = ""

    # B2B fields (populated when this number belongs to a business campaign)
    is_b2b_customer: bool = False
    business_id: Optional[str] = None
    campaign_id: Optional[str] = None

    # Privacy
    memory_enabled: bool = True                  # User can disable memory
    consent_given_at: Optional[datetime] = None

    def to_context_blob(self) -> str:
        """Light, natural context for the LLM. Avoids creepy or overly detailed memory."""
        parts = []

        if self.name:
            parts.append(f"The caller's name is {self.name}.")
        if self.personality and self.personality != "friendly":
            parts.append(f"Respond in a {self.personality} tone.")
        if self.language:
            parts.append(f"Preferred language: {self.language}.")

        # Only include light, useful recent context
        if self.rolling_summary and len(self.rolling_summary) > 15:
            summary = self.rolling_summary[:160]
            parts.append(f"Quick context: {summary}")

        if self.recent_facts:
            useful_facts = [f for f in self.recent_facts[:2] if len(f) > 5]
            if useful_facts:
                parts.append("Things mentioned before: " + "; ".join(useful_facts))

        # Structured daily goals and reminders (light context)
        active_goals = [g.text for g in self.daily_goals if g.status == "pending"][:3]
        if active_goals:
            parts.append("Today's goals: " + "; ".join(active_goals))

        active_reminders = [r.text for r in self.reminders if r.is_active][:2]
        if active_reminders:
            parts.append("Active reminders: " + "; ".join(active_reminders))

        if not parts:
            return "This is a returning caller."

        return " ".join(parts)