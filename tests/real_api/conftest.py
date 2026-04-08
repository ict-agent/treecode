"""Real API / subprocess integration tests — opt-in only.

The ``tests/real_api/`` package is **ignored by default** (see root ``tests/conftest.py``).
Enable collection with::

    export OPENHARNESS_RUN_REAL_API_TESTS=1
    export ANTHROPIC_API_KEY=sk-...
    uv run pytest tests/real_api/

Or::

    uv run python scripts/run_real_api_tests.py

Optional workspace: ``OPENHARNESS_REAL_API_WORKSPACE``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.real_api.env import anthropic_api_configured, workspace_path

# ---------------------------------------------------------------------------
# Skip entire package when no API key
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if anthropic_api_configured():
        return
    skip = pytest.mark.skip(
        reason=(
            "needs ANTHROPIC_API_KEY (set in environment to run tests/real_api/)"
        )
    )
    for item in items:
        if _item_is_under_real_api(item):
            item.add_marker(skip)


def _item_is_under_real_api(item: pytest.Item) -> bool:
    path = getattr(item, "path", None)
    if path is None:
        fspath = getattr(item, "fspath", None)
        path = Path(str(fspath)) if fspath is not None else None
    if path is None:
        return False
    return "real_api" in Path(path).resolve().parts


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "needs_workspace: test requires OPENHARNESS_REAL_API_WORKSPACE to exist on disk",
    )


@pytest.fixture
def real_api_workspace_dir() -> Path:
    """Skip if workspace path is missing (tests that need a real tree)."""
    p = workspace_path()
    if not p.is_dir():
        pytest.skip(
            f"needs existing OPENHARNESS_REAL_API_WORKSPACE directory (got {p})"
        )
    return p


# Backwards-compatible alias for imports
def real_api_workspace() -> Path:
    return workspace_path()
