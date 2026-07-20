"""
config.py - Centralized configuration for the AI Phone Assistant Platform
Phase 1: B2C-first with multi-tenant architecture ready for B2B
"""

import os
from dataclasses import dataclass, field
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

# ==================== LANGUAGES (Day 1 Support) ====================
SUPPORTED_LANGUAGES = {
    "hi-IN": "Hindi",
    "te-IN": "Telugu",
    "en-IN": "English"
}

DEFAULT_LANGUAGE = "hi-IN"

# ==================== VOICES (B2C Onboarding + B2B Choice) ====================
# These must match actual Sarvam TTS voice IDs
FEMALE_VOICES = {
    "anushka": "Anushka (Warm & friendly female)",
    "manisha": "Manisha (Clear & professional female)",
    "vidya": "Vidya (Mature & calm female)",
    "arya": "Arya (Young & energetic female)"
}

MALE_VOICES = {
    "abhilash": "Abhilash (Warm & friendly male)",
    "karun": "Karun (Deep & calm male)",
    "hitesh": "Hitesh (Clear & professional male)"
}

ALL_VOICES = {**FEMALE_VOICES, **MALE_VOICES}
DEFAULT_VOICE = "anushka"

# ==================== SAFETY CONFIG ====================
SAFETY_MODE: Literal["soft_redirect", "hard_block"] = "soft_redirect"
SAFE_FOR_ALL_AGES: bool = True

# Emergency / Helpline numbers
EMERGENCY_CONTACTS = {
    "general": "112",
    "mental_health_tele_manas": "14416",
    "mental_health_kiran": "1800-599-0019"
}

# ==================== PRODUCT CONFIG ====================
@dataclass
class ProductConfig:
    free_minutes_per_day: int = int(os.environ.get("FREE_MINUTES_PER_DAY", 10))
    max_recent_facts: int = 8
    history_turns_kept: int = 6
    supported_languages: dict = field(default_factory=lambda: SUPPORTED_LANGUAGES)
    default_language: str = DEFAULT_LANGUAGE

PRODUCT = ProductConfig()

# ==================== API KEYS & INFRA ====================
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # optional; no longer required for main path

# Sarvam LLM (OpenAI-compatible). Allowed by pipecat SarvamLLMService:
#   sarvam-30b, sarvam-30b-16k, sarvam-105b, sarvam-105b-32k
SARVAM_LLM_MODEL = os.environ.get("SARVAM_LLM_MODEL", "sarvam-30b")
SARVAM_LLM_BASE_URL = os.environ.get("SARVAM_LLM_BASE_URL", "https://api.sarvam.ai/v1")

WS_HOST = os.environ.get("WS_HOST", "0.0.0.0")
WS_PORT = int(os.environ.get("WS_PORT", 8765))
EXOTEL_SAMPLE_RATE = int(os.environ.get("EXOTEL_SAMPLE_RATE", 8000))  # standard telephony rate; pipeline.py should import this rather than hardcoding 8000 separately

print("[config] Configuration loaded successfully")
print(
    f"[config] Languages: {list(SUPPORTED_LANGUAGES.keys())} | "
    f"LLM: {SARVAM_LLM_MODEL} | Safety: {SAFETY_MODE} (All ages: {SAFE_FOR_ALL_AGES})"
)