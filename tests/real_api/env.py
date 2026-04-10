"""Environment and paths for ``tests/real_api/`` (imported by conftest and test modules)."""

from __future__ import annotations

import os
from pathlib import Path


def workspace_path() -> Path:
    """Large-repo cwd (e.g. AutoAgent checkout). Override with TREECODE_REAL_API_WORKSPACE."""
    return Path(os.environ.get("TREECODE_REAL_API_WORKSPACE", "/home/tangjiabin/AutoAgent")).expanduser()


def anthropic_api_configured() -> bool:
    """True when ANTHROPIC_API_KEY looks usable (no empty / placeholder)."""
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return False
    lowered = key.lower()
    if lowered.startswith("sk-your-") or lowered in {"your-api-key-here", "test"}:
        return False
    return True


def api_key() -> str:
    """Return API key or raise RuntimeError (call only when anthropic_api_configured())."""
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return key
