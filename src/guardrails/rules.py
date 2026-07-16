"""
rules.py - Safety rules, patterns, and soft redirect messages
Safe for all ages + soft empathetic redirect approach
"""

import re
from ..config import EMERGENCY_CONTACTS

# ==================== EMERGENCY / CRISIS ====================
EMERGENCY_PATTERNS = [
    re.compile(r"suicide|kill myself|end my life|want to die", re.IGNORECASE),
    re.compile(r"self.?harm|hurt myself|cut myself", re.IGNORECASE),
    re.compile(r"heart attack|can't breathe|severe bleeding|serious accident", re.IGNORECASE),
    re.compile(r"medical emergency|dying|going to die", re.IGNORECASE),
]

def is_emergency(text: str) -> bool:
    return any(p.search(text) for p in EMERGENCY_PATTERNS)

CRISIS_REDIRECT = (
    "I hear you, and I'm really glad you shared this with me. "
    "This feels bigger than what I can help with right now. "
    f"Please reach out to Tele MANAS at {EMERGENCY_CONTACTS['mental_health_tele_manas']} — "
    "they're available 24/7 and can support you properly. "
    "Would you like me to repeat the number?"
)

# ==================== ABUSE / HARASSMENT ====================
ABUSE_PATTERNS = [
    re.compile(r"\b(fuck you|bastard|idiot|stupid|shut up)\b", re.IGNORECASE),
]

def is_abusive(text: str) -> bool:
    return any(p.search(text) for p in ABUSE_PATTERNS)

ABUSE_REDIRECT = (
    "I understand you're feeling frustrated. "
    "I'm here to help, but I can't continue if the language becomes hurtful. "
    "Let's try again — what can I assist you with?"
)

# ==================== SEXUAL / ROMANTIC CONTENT ====================
# Broad detection because age verification on phone is unreliable
SEXUAL_PATTERNS = [
    re.compile(r"\b(sex|sexy|porn|naked|nude|fuck|make love|romantic|kiss|date me|girlfriend|boyfriend)\b", re.IGNORECASE),
    re.compile(r"i love you|do you love me|are you single", re.IGNORECASE),
]

def contains_sexual_content(text: str) -> bool:
    return any(p.search(text) for p in SEXUAL_PATTERNS)

SEXUAL_REDIRECT = (
    "I appreciate you sharing that, but I'm an AI assistant designed to help with practical things "
    "like information, reminders, or general conversation. "
    "I'm not the right person for romantic or personal topics. "
    "Is there something else I can help you with today?"
)

# ==================== HARM TO OTHERS / ANIMALS ====================
HARM_PATTERNS = [
    re.compile(r"hurt (someone|animal|dog|cat|person)|kill (animal|dog|cat)", re.IGNORECASE),
    re.compile(r"violence|beat up|attack someone", re.IGNORECASE),
]

def contains_harm_content(text: str) -> bool:
    return any(p.search(text) for p in HARM_PATTERNS)

HARM_REDIRECT = (
    "I can't help with anything that could harm someone or an animal. "
    "If you're going through something difficult, I'm here to listen, "
    "but I won't engage with harmful ideas. "
    "Would you like to talk about something else?"
)

# ==================== GENERAL SOFT REDIRECT ====================
GENERAL_UNSAFE_REDIRECT = (
    "I want to be helpful, but I need to stay within safe topics. "
    "Let's talk about something else — how can I assist you today?"
)

def get_soft_redirect(category: str) -> str:
    """Return appropriate soft redirect message"""
    redirects = {
        "sexual": SEXUAL_REDIRECT,
        "abuse": ABUSE_REDIRECT,
        "harm": HARM_REDIRECT,
        "crisis": CRISIS_REDIRECT,
        "general": GENERAL_UNSAFE_REDIRECT,
    }
    return redirects.get(category, GENERAL_UNSAFE_REDIRECT)