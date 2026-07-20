"""
prompt_manager.py - Load and cache prompts in memory at startup
This solves the synchronous file I/O risk flagged in production reviews.

Supports nested structure: prompts/voice/system_prompt.txt etc.
Lookup is by basename (system_prompt.txt) so callers stay simple.
"""

import os
from typing import Dict

_prompt_cache: Dict[str, str] = {}


def load_prompts() -> None:
    """Load all .txt prompts recursively into memory once at startup."""
    global _prompt_cache
    prompt_dir = "prompts"

    if not os.path.exists(prompt_dir):
        # Also try relative to this file (common when running as module)
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "..", "..", "prompts"),
            os.path.join(here, "..", "prompts"),
            "prompts",
        ]
        for cand in candidates:
            if os.path.exists(cand):
                prompt_dir = cand
                break
        else:
            print("[prompt_manager] prompts/ directory not found. Using defaults.")
            return

    for root, _dirs, files in os.walk(prompt_dir):
        for filename in files:
            if filename.endswith(".txt"):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    # Key by basename so get_prompt("system_prompt.txt") works
                    # regardless of whether it lives in prompts/ or prompts/voice/
                    _prompt_cache[filename] = content
                    # Also allow full relative path key for future flexibility
                    rel = os.path.relpath(filepath, prompt_dir)
                    _prompt_cache[rel] = content
                    print(f"[prompt_manager] Loaded and cached: {rel}")
                except Exception as e:
                    print(f"[prompt_manager] Failed to load {filepath}: {e}")


def get_prompt(name: str) -> str:
    """Get a cached prompt by basename or relative path. Empty string if missing."""
    return _prompt_cache.get(name, "")


# Auto-load on import (safe because it's just reading files once)
load_prompts()
