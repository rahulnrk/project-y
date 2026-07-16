"""
reminder_scheduler.py - Basic time-aware reminder checking
For MVP: Checks reminders when user calls in. Full background scheduling can be added later.
"""

from datetime import datetime
from typing import List
from ..models.caller_profile import Reminder


def get_due_reminders(reminders: List[Reminder]) -> List[Reminder]:
    """
    Simple MVP logic: Return active reminders.
    In future, we can add time comparison (e.g., evening reminders at night).
    """
    now = datetime.now()
    due = []
    for reminder in reminders:
        if not reminder.is_active:
            continue
        # For MVP, we consider all active reminders as "due" when user calls
        # Later we can add time-window logic
        due.append(reminder)
    return due[:3]  # Limit to 3 reminders per call


def format_reminders_for_speech(reminders: List[Reminder]) -> str:
    """Convert reminders into natural spoken text"""
    if not reminders:
        return ""
    texts = [r.text for r in reminders]
    if len(texts) == 1:
        return f"Yaad rakhna: {texts[0]}."
    return "Yaad rakhna: " + ", ".join(texts[:-1]) + f", aur {texts[-1]}."