"""Unit tests for safety rules."""

from src.guardrails.rules import (
    is_emergency,
    is_abusive,
    contains_sexual_content,
    contains_harm_content,
    get_soft_redirect,
)


def test_emergency_detection():
    assert is_emergency("I want to die")
    assert is_emergency("thinking about suicide")
    assert not is_emergency("I want to plan my day")


def test_sexual_detection():
    assert contains_sexual_content("will you be my girlfriend")
    assert not contains_sexual_content("remind me to call mom")


def test_abuse_detection():
    assert is_abusive("shut up you idiot")
    assert not is_abusive("hello how are you")


def test_harm_detection():
    assert contains_harm_content("how to hurt someone")
    assert not contains_harm_content("hurt feelings after exam")


def test_soft_redirects():
    for cat in ("crisis", "sexual", "harm", "abuse", "general"):
        msg = get_soft_redirect(cat)
        assert isinstance(msg, str) and len(msg) > 20
    assert "Tele MANAS" in get_soft_redirect("crisis") or "14416" in get_soft_redirect("crisis")
