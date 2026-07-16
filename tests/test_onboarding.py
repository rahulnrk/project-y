"""Unit tests for onboarding flow."""

import pytest

from src.core.onboarding import extract_name_with_llm, handle_onboarding_turn
from src.models.caller_profile import CallerProfile


@pytest.mark.asyncio
async def test_extract_name_english():
    assert await extract_name_with_llm("My name is Priya") == "Priya"
    assert await extract_name_with_llm("I am Sarah") == "Sarah"
    assert await extract_name_with_llm("Rahul") == "Rahul"


@pytest.mark.asyncio
async def test_extract_name_hindi_style():
    name = await extract_name_with_llm("mera naam Amit hai")
    assert "Amit" in name


@pytest.mark.asyncio
async def test_onboarding_flow():
    profile = CallerProfile(phone_number="919876543210")

    reply0, done0 = await handle_onboarding_turn(profile, "", 0)
    assert done0 is False
    assert "naam" in reply0.lower() or "Namaste" in reply0

    reply1, done1 = await handle_onboarding_turn(profile, "My name is Priya", 1)
    assert done1 is False
    assert profile.name == "Priya"
    assert "bhasha" in reply1.lower() or "Hindi" in reply1

    reply2, done2 = await handle_onboarding_turn(profile, "Hindi", 2)
    assert done2 is True
    assert profile.language == "hi-IN"
    assert "yahin" in reply2.lower() or "Planning" in reply2


@pytest.mark.asyncio
async def test_language_telugu_english():
    profile = CallerProfile(phone_number="91")
    profile.name = "Test"
    _, done = await handle_onboarding_turn(profile, "Telugu", 2)
    assert done is True
    assert profile.language == "te-IN"

    profile2 = CallerProfile(phone_number="92")
    profile2.name = "Test"
    await handle_onboarding_turn(profile2, "English", 2)
    assert profile2.language == "en-IN"
