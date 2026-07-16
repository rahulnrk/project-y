"""
prompt_manager.py - Load and cache prompts in memory at startup
This solves the synchronous file I/O risk flagged in production reviews.
"""

import os
from typing import Dict

_prompt_cache: Dict[str, str] = {}


def load_prompts() -> None:
    """Load all prompts into memory once at startup."""
    global _prompt_cache
    prompt_dir = "prompts"

    if not os.path.exists(prompt_dir):
        print("[prompt_manager] prompts/ directory not found. Using defaults.")
        return

    for filename in os.listdir(prompt_dir):
        if filename.endswith(".txt"):
            filepath = os.path.join(prompt_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    _prompt_cache[filename] = f.read()
                print(f"[prompt_manager] Loaded and cached: {filename}")
            except Exception as e:
                print(f"[prompt_manager] Failed to load {filename}: {e}")


def get_prompt(name: str) -> str:
    """Get a cached prompt. Falls back to empty string if missing."""
    return _prompt_cache.get(name, "")


# Auto-load on import (safe because it's just reading files once)
load_prompts()