"""
prompt_manager.py - Load and cache prompts in memory at startup
This solves the synchronous file I/O risk flagged in production reviews.
"""

import os
from pathlib import Path
from typing import Dict

_prompt_cache: Dict[str, str] = {}


def _project_root() -> Path:
    # src/utils/prompt_manager.py -> project root
    return Path(__file__).resolve().parents[2]


def load_prompts() -> None:
    """Load all .txt prompts into memory once at startup (including voice/)."""
    global _prompt_cache
    roots = [
        _project_root() / "prompts",
        Path.cwd() / "prompts",
    ]

    loaded_any = False
    for prompt_dir in roots:
        if not prompt_dir.is_dir():
            continue
        for path in prompt_dir.rglob("*.txt"):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"[prompt_manager] Failed to load {path}: {e}")
                continue
            # Cache by basename and relative path so both work:
            # get_prompt("system_prompt.txt") and get_prompt("voice/system_prompt.txt")
            _prompt_cache[path.name] = text
            try:
                rel = str(path.relative_to(prompt_dir)).replace("\\", "/")
                _prompt_cache[rel] = text
            except ValueError:
                pass
            print(f"[prompt_manager] Loaded and cached: {path.name} ({path})")
            loaded_any = True
        if loaded_any:
            break

    if not loaded_any:
        print("[prompt_manager] prompts/ directory not found. Using defaults.")


def get_prompt(name: str) -> str:
    """Get a cached prompt. Falls back to empty string if missing."""
    return _prompt_cache.get(name, "")


# Auto-load on import (safe because it's just reading files once)
load_prompts()
