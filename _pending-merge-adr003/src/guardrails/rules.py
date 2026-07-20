"""
rules.py – Safety rules, vernacular patterns, and soft redirects
India-first: Hindi + Telugu + Hinglish + English
Safe-for-all-ages + soft empathetic tone

High-severity (medical, mental crisis, clear sexual, clear harm threats)
must suppress the LLM turn. Medium-severity (abuse) stays parallel.
"""

import re
from dataclasses import dataclass
from typing import Optional, Literal

from ..config import EMERGENCY_CONTACTS


# ---------------------------------------------------------------------------
# Result object returned by the classifier
# ---------------------------------------------------------------------------
@dataclass
class SafetyResult:
    category: str                          # mental_crisis | medical_emergency | sexual | harm | abuse
    severity: Literal["high", "medium"]
    helpline: Optional[str]                # "14416" | "112" | None
    redirect_text: str
    should_suppress_llm: bool              # True → do NOT push TranscriptionFrame


# ---------------------------------------------------------------------------
# Patterns – medical checked before mental crisis
# ---------------------------------------------------------------------------

# --- Medical emergencies → 112 ---
MEDICAL_PATTERNS = [
    # English
    re.compile(
        r"\b(heart attack|can't breathe|cannot breathe|severe bleeding|"
        r"chest pain|unconscious|stroke|serious accident|medical emergency|"
        r"not breathing|heavy bleeding|collapsed|having a heart attack)\b",
        re.IGNORECASE,
    ),
    # Hinglish
    re.compile(
        r"\b(dil ka daura|saans nahi|saans nahi aa rahi|bahut khoon|"
        r"seene mein dard|behosh|lakwa|medical emergency|dil ka dard)\b",
        re.IGNORECASE,
    ),
    # Hindi
    re.compile(
        r"(दिल का दौरा|सांस नहीं आ रही|सांस नहीं|बहुत खून|"
        r"सीने में दर्द|बेहोश|लकवा|मेडिकल इमरजेंसी|दिल का दर्द)",
        re.IGNORECASE,
    ),
    # Telugu
    re.compile(
        r"(గుండెపోటు|ఊపిరి ఆడటం లేదు|తీవ్ర రక్తస్రావం|"
        r"ఛాతీ నొప్పి|స్పృహ లేకుండా|వైద్య అత్యవసరం|గుండె నొప్పి)",
        re.IGNORECASE,
    ),
]

# --- Mental crisis / self-harm → Tele MANAS 14416 ---
MENTAL_CRISIS_PATTERNS = [
    # English
    re.compile(
        r"\b(suicide|kill myself|end my life|want to die|self.?harm|"
        r"hurt myself|cut myself|ending it all|no reason to live|"
        r"take my own life|commit suicide)\b",
        re.IGNORECASE,
    ),
    # Hinglish
    re.compile(
        r"\b(suicide kar|khud ko maar|marna chahta|marna chahti|"
        r"aatmahatya|self harm|khudkhushi|jaan de dena|mar jaana chahta|"
        r"suicide kar lunga|khud ko khatam)\b",
        re.IGNORECASE,
    ),
    # Hindi
    re.compile(
        r"(आत्महत्या|खुद को मार|मरना चाहता|मरना चाहती|"
        r"खुदकुशी|जान दे देना|सेल्फ हार्म|मर जाऊं|खुद को खत्म)",
        re.IGNORECASE,
    ),
    # Telugu
    re.compile(
        r"(ఆత్మహత్య|నన్ను చంపుకో|మరణించాలి|చావాలని|"
        r"సెల్ఫ్ హార్మ్|ఆత్మహత్య చేసుకో|చనిపోవాలని)",
        re.IGNORECASE,
    ),
]

# --- Clear sexual content (high severity) ---
SEXUAL_PATTERNS = [
    # English + Hinglish
    re.compile(
        r"\b(sex|sexy|porn|naked|nude|fuck me|make love|blowjob|"
        r"handjob|oral sex|sex kar|porn dekh|naked photo|kiss me hard|"
        r"girlfriend bana|boyfriend bana|sex chat|sex karenge)\b",
        re.IGNORECASE,
    ),
    # Hindi
    re.compile(
        r"(सेक्स|सेक्सी|पोर्न|नग्न|न्यूड|चोदो|सेक्स कर|"
        r"पोर्न देख|नंगी फोटो|सेक्स चैट)",
        re.IGNORECASE,
    ),
    # Telugu
    re.compile(
        r"(సెక్స్|పోర్న్|నగ్న|సెక్స్ చేయ్|పోర్న్ చూడు|సెక్స్ చాట్)",
        re.IGNORECASE,
    ),
]

# --- Clear threats of harm to others/animals (high) ---
HARM_PATTERNS = [
    # English + Hinglish
    re.compile(
        r"\b(kill (him|her|them|someone)|hurt (him|her|them|someone)|"
        r"beat up|attack someone|maar dunga|maar doonga|maar dalunga|"
        r"violence karna|kisi ko maar|main usko maar)\b",
        re.IGNORECASE,
    ),
    # Hindi
    re.compile(
        r"(मार डालूंगा|मार दूंगा|हिंसा|किसी को मार|"
        r"नुकसान पहुंचाऊंगा|मैं उसे मार)",
        re.IGNORECASE,
    ),
    # Telugu
    re.compile(
        r"(చంపేస్తాను|హింస|ఎవరినైనా దెబ్బతీస్తాను|చంపేయాలి)",
        re.IGNORECASE,
    ),
]

# --- Abuse / mild harassment (medium) ---
ABUSE_PATTERNS = [
    re.compile(
        r"\b(fuck you|bastard|idiot|stupid|shut up|madarchod|"
        r"behenchod|chutiya|saale|kamine|gandu)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(मादरचोद|बहनचोद|चूतिया|साले|कमीने|गांडू)",
        re.IGNORECASE,
    ),
]


# ---------------------------------------------------------------------------
# Redirect messages (warm, soft, supportive)
# ---------------------------------------------------------------------------

MEDICAL_REDIRECT = (
    "This sounds like a medical emergency. "
    f"Please call 112 right now for immediate help. "
    "The number is one-one-two. Stay as calm as you can and get help."
)

MENTAL_CRISIS_REDIRECT = (
    "I hear you, and I'm really glad you shared this with me. "
    "This feels bigger than what I can help with right now. "
    f"Please reach out to Tele MANAS at {EMERGENCY_CONTACTS['mental_health_tele_manas']} — "
    "they're available 24/7 and can support you properly. "
    "Would you like me to repeat the number?"
)

SEXUAL_REDIRECT = (
    "I appreciate you sharing that, but I'm an AI assistant designed to help "
    "with practical things like information, reminders, or general conversation. "
    "I'm not the right person for romantic or personal topics. "
    "Is there something else I can help you with today?"
)

HARM_REDIRECT = (
    "I can't help with anything that could harm someone or an animal. "
    "If you're going through something difficult, I'm here to listen, "
    "but I won't engage with harmful ideas. "
    "Would you like to talk about something else?"
)

ABUSE_REDIRECT = (
    "I understand you're feeling frustrated. "
    "I'm here to help, but I can't continue if the language becomes hurtful. "
    "Let's try again — what can I assist you with?"
)


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_safety(text: str) -> Optional[SafetyResult]:
    """
    Returns SafetyResult for high/medium severity content, else None.
    Order matters: medical first, then mental crisis, then sexual/harm, then abuse.
    """
    if not text or not text.strip():
        return None

    t = text.strip()

    # 1. Medical emergency (high) → 112
    if any(p.search(t) for p in MEDICAL_PATTERNS):
        return SafetyResult(
            category="medical_emergency",
            severity="high",
            helpline="112",
            redirect_text=MEDICAL_REDIRECT,
            should_suppress_llm=True,
        )

    # 2. Mental crisis / self-harm (high) → Tele MANAS
    if any(p.search(t) for p in MENTAL_CRISIS_PATTERNS):
        return SafetyResult(
            category="mental_crisis",
            severity="high",
            helpline="14416",
            redirect_text=MENTAL_CRISIS_REDIRECT,
            should_suppress_llm=True,
        )

    # 3. Clear sexual content (high)
    if any(p.search(t) for p in SEXUAL_PATTERNS):
        return SafetyResult(
            category="sexual",
            severity="high",
            helpline=None,
            redirect_text=SEXUAL_REDIRECT,
            should_suppress_llm=True,
        )

    # 4. Clear threats of harm (high)
    if any(p.search(t) for p in HARM_PATTERNS):
        return SafetyResult(
            category="harm",
            severity="high",
            helpline=None,
            redirect_text=HARM_REDIRECT,
            should_suppress_llm=True,
        )

    # 5. Abuse (medium) – parallel soft redirect only
    if any(p.search(t) for p in ABUSE_PATTERNS):
        return SafetyResult(
            category="abuse",
            severity="medium",
            helpline=None,
            redirect_text=ABUSE_REDIRECT,
            should_suppress_llm=False,
        )

    return None
