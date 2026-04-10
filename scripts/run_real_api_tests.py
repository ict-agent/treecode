#!/usr/bin/env python3
"""Driver for tests/real_api/ — requires ANTHROPIC_API_KEY in the environment.

Usage (from repo root):
  export ANTHROPIC_API_KEY=sk-...
  # optional:
  # export TREECODE_REAL_API_WORKSPACE=/path/to/large-repo
  # export ANTHROPIC_BASE_URL=https://...
  uv run python scripts/run_real_api_tests.py
  uv run python scripts/run_real_api_tests.py -q --tb=short -x
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        print(
            "error: ANTHROPIC_API_KEY is not set; real API tests are skipped or will fail.\n"
            "  export ANTHROPIC_API_KEY=sk-...\n"
            "  uv run python scripts/run_real_api_tests.py",
            file=sys.stderr,
        )
        return 2
    os.environ.setdefault("TREECODE_RUN_REAL_API_TESTS", "1")
    os.chdir(root)
    import pytest

    args = [str(root / "tests" / "real_api")] + sys.argv[1:]
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
