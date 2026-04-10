"""Shared test fixtures and collection policy.

Real API / subprocess integration lives in ``tests/real_api/``. That tree is **not
collected** unless ``TREECODE_RUN_REAL_API_TESTS=1`` is set, so a plain
``pytest`` never imports or runs those modules (avoids hangs from LLM/subprocess).

To run them explicitly::

    export TREECODE_RUN_REAL_API_TESTS=1
    export ANTHROPIC_API_KEY=sk-...
    uv run pytest tests/real_api/

Process-level safety net (kills the whole run if something still blocks)::

    timeout 600 uv run pytest tests/
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Env vars that merge into Settings via load_settings() — if set in the developer shell,
# tests that expect isolated tmp config files would flake. Strip before each test.
_SETTINGS_ENV_KEYS = (
    "ANTHROPIC_MODEL",
    "TREECODE_MODEL",
    "ANTHROPIC_BASE_URL",
    "TREECODE_BASE_URL",
    "TREECODE_MAX_TOKENS",
    "TREECODE_MAX_TURNS",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "TREECODE_API_FORMAT",
)


@pytest.fixture(autouse=True)
def _isolate_treecode_settings_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    # Real API tests under tests/real_api/ need ANTHROPIC_* left to user env.
    if "real_api" in getattr(request.node, "nodeid", ""):
        return
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Do not collect tests/real_api/ unless opt-in (stronger than skip: no import).
# ---------------------------------------------------------------------------


def pytest_ignore_collect(collection_path: Path, config):  # type: ignore[no-untyped-def]
    if os.environ.get("TREECODE_RUN_REAL_API_TESTS", "").lower() in ("1", "true", "yes"):
        return None
    try:
        parts = collection_path.resolve().parts
    except OSError:
        return None
    if "real_api" in parts:
        return True
    return None
