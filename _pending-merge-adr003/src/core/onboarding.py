"""
onboarding.py - First-call introduction and data collection flow
Collects: name, age, gender, voice preference, language
"""

import re

from ..config import ALL_VOICES, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, DEFAULT_VOICE

# Common lead-in phrases people actually use when stating their name, tried in
# order. The old approach (strip filler words, take the first word left over)
# returned "Is" for "My name is Priya" and "I" for "I am Sarah" -- tested
# before writing this, not guessed.
_NAME_PATTERNS = [
    r"(?:my name is|i am|i'm|this is)\s+(.+)",
    r"(?:mera naam|naam mera)\s+(.+?)(?:\s+hai)?$",
    r"(?:main)\s+(.+?)(?:\s+hoon)?$",
]


ONBOARDING_INTRO = (
    "Namaste! Main aapka personal AI assistant hoon. "
    "Main aapki baat yaad rakh sakta hoon taaki agli baar behtar madad kar sakoon. "
    "Pehle kuch basic baatein samajh lete hain."
)

def get_voice_selection_prompt() -> str:
    """Generate voice selection message"""
    voices_text = ", ".join([f"{name} ({desc})" for name, desc in list(ALL_VOICES.items())[:4]])
    return (
        f"Aap kis voice mein baat karna pasand karenge? "
        f"Mere paas ye options hain: {voices_text}. "
        f"Aap male ya female voice choose kar sakte hain."
    )

def get_language_prompt() -> str:
    return (
        "Aap kis bhasha mein baat karna pasand karenge? "
        "Hindi, Telugu, ya English? Main teeno support karta hoon."
    )

async def extract_name_with_llm(user_text: str) -> str:
    """Heuristic name extraction (still worth upgrading to a real fast-model
    call later -- this covers the common phrasings, not every phrasing)."""
    text = user_text.strip()
    lowered = text.lower()
    for pattern in _NAME_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            candidate = match.group(1).strip().rstrip(".,!")
            if candidate:
                return candidate.title()
    # No known lead-in phrase matched -- assume the whole utterance is the
    # name (handles a caller just saying their name alone), rather than
    # guessing at a single leftover word.
    cleaned = text.rstrip(".,!")
    return cleaned.title() if cleaned else "unknown"


async def handle_onboarding_turn(
    profile, 
    user_text: str, 
    turn_number: int
) -> tuple[str, bool]:
    """
    Shortened onboarding flow (2-3 turns max).
    Collects: Name → Language → "How can I help?"
    Voice & Personality are asked later or on subsequent calls.
    """
    text = user_text.lower().strip()

    # Turn 0: Natural, simple welcome + Ask name
    if turn_number == 0:
        return (
            "Namaste! Main aapka personal AI assistant hoon. "
            "Main aapki baat yaad rakhunga. "
            "Aapka naam kya hai?"
        ), False

    # Turn 1: Name + Ask language naturally
    if turn_number == 1 and not profile.name:
        extracted = await extract_name_with_llm(user_text)
        if extracted != "unknown":
            profile.name = extracted
            return (
                f"Theek hai {profile.name}. "
                "Aap kis bhasha mein baat karna pasand karenge? Hindi, Telugu, ya English?"
            ), False
        else:
            return "Sorry, naam samajh nahi aaya. Phir se bataiye?", False

    # Turn 2: Language + Finish onboarding naturally
    if turn_number == 2:
        if any(w in text for w in ["hindi", "हिंदी"]):
            profile.language = "hi-IN"
        elif any(w in text for w in ["telugu", "తెలుగు"]):
            profile.language = "te-IN"
        elif any(w in text for w in ["english", "अंग्रेजी"]):
            profile.language = "en-IN"
        else:
            profile.language = DEFAULT_LANGUAGE

        return (
            f"Accha. Ab main yahin hoon. "
            "Kuch baat karni hai aaj? Planning, reminders, ya kuch aur?",
            True
        )

    return "Maaf kijiye, main thoda confuse ho gaya. Phir se bataiye?", False