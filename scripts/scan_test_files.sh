#!/usr/bin/env bash
# Scan each tests/**/test_*.py with a 10s wall-clock cap per file.
# OK   = finished within 10s (any exit code except 124)
# HANG = GNU timeout exit 124 — file still running after 10s (often too many/slow tests or blocked I/O)
#
# Usage: ./scripts/scan_test_files.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

while IFS= read -r -d '' f; do
  printf '%-58s ' "$f"
  if timeout 10s uv run pytest -q "$f" >"$tmp" 2>&1; then
    echo "OK"
  else
    ec=$?
    if [[ "$ec" -eq 124 ]]; then
      echo "TIMEOUT_OR_SLOW (>10s wall)"
    else
      echo "DONE_FAIL (exit $ec)"
      tail -4 "$tmp" | sed 's/^/  | /'
    fi
  fi
done < <(find tests -name 'test_*.py' -print0 | sort -z)
