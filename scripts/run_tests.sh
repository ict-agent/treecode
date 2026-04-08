#!/usr/bin/env bash
# Default unit/integration test run: does NOT collect tests/real_api/ (see tests/conftest.py).
# Wall-clock cap on the entire pytest process — last resort if something still blocks.
#
#   ./scripts/run_tests.sh
#   PYTEST_TIMEOUT_SECONDS=300 ./scripts/run_tests.sh -v
#
set -euo pipefail
cd "$(dirname "$0")/.."
sec="${PYTEST_TIMEOUT_SECONDS:-600}"
exec timeout "$sec" uv run pytest tests/ "$@"
