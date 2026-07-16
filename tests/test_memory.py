"""Unit tests for MemoryStore using fakeredis."""

import pytest
import fakeredis.aioredis

from src.memory.memory_store import MemoryStore, summarize_call
from src.models.caller_profile import CallerProfile


@pytest.fixture
async def store():
    s = MemoryStore.__new__(MemoryStore)
    s._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    s._max_recent_facts = 8
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_start_call_creates_profile(store):
    # Key is digits-only; same digit string must hit the same profile.
    # Note: "+91 98765 43210" and "9876543210" are different digit keys today
    # (country-code normalization is a known product gap).
    profile = await store.start_call("+91 98765 43210")
    assert profile.total_calls == 1
    assert profile.first_call_at is not None
    assert profile.last_call_at is not None

    profile2 = await store.start_call("91-98765-43210")
    assert profile2.total_calls == 2
    assert profile2.first_call_at == profile.first_call_at


@pytest.mark.asyncio
async def test_append_and_read_summary(store):
    await store.start_call("999")
    await store.append_call_summary(
        "999",
        new_facts=["likes morning walks", "works in Hyderabad"],
        updated_rolling_summary="Caller enjoys morning walks in Hyderabad.",
    )
    profile = await store.get_profile("999")
    assert "morning walks" in profile.rolling_summary
    assert profile.recent_facts[0] == "likes morning walks"
    assert len(profile.recent_facts) == 2


@pytest.mark.asyncio
async def test_delete_user_data(store):
    await store.start_call("111")
    assert await store.delete_user_data("111") is True
    profile = await store.get_profile("111")
    assert profile.total_calls == 0
    assert profile.rolling_summary == ""


@pytest.mark.asyncio
async def test_update_voice_preference(store):
    await store.start_call("222")
    await store.update_voice_preference("222", "abhilash")
    profile = await store.get_profile("222")
    assert profile.voice_id == "abhilash"

    await store.update_voice_preference("222", "not-a-real-voice")
    profile = await store.get_profile("222")
    assert profile.voice_id == "abhilash"  # unchanged


@pytest.mark.asyncio
async def test_summarize_call_parses_json():
    async def fake_llm(prompt: str) -> str:
        return '{"summary": "Caller is Priya from Delhi.", "facts": ["lives in Delhi"]}'

    summary, facts = await summarize_call(fake_llm, "user: hi\nassistant: hello", "")
    assert "Priya" in summary
    assert facts == ["lives in Delhi"]


@pytest.mark.asyncio
async def test_summarize_call_bad_json_keeps_previous():
    async def bad_llm(prompt: str) -> str:
        return "not-json"

    summary, facts = await summarize_call(bad_llm, "transcript", "old summary")
    assert summary == "old summary"
    assert facts == []


def test_context_blob_includes_name_and_facts():
    p = CallerProfile(
        phone_number="1",
        name="Priya",
        language="hi-IN",
        rolling_summary="Enjoys evening walks and tea.",
        recent_facts=["works in product", "likes chai"],
    )
    blob = p.to_context_blob()
    assert "Priya" in blob
    assert "chai" in blob or "product" in blob
