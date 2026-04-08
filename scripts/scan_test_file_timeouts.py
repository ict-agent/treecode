#!/usr/bin/env python3
"""Run pytest one file at a time with a wall-clock cap; find slow/hanging modules.

Usage (from repo root):
  uv run python scripts/scan_test_file_timeouts.py
  uv run python scripts/scan_test_file_timeouts.py --timeout 25
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=35.0, help="Seconds per file (default 35)")
    parser.add_argument("--pytest", default="uv run pytest -q", help="pytest invocation prefix")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    tests = sorted(root.glob("tests/**/test_*.py"))
    if not tests:
        print("No tests/**/test_*.py found", file=sys.stderr)
        return 1

    cmd_prefix = args.pytest.split()
    timeout = args.timeout

    ok: list[str] = []
    timed_out: list[str] = []
    failed: list[str] = []

    for path in tests:
        rel = path.relative_to(root)
        argv = cmd_prefix + [str(rel)]
        try:
            r = subprocess.run(
                argv,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            timed_out.append(str(rel))
            print(f"TIMEOUT  >{timeout}s  {rel}", flush=True)
            continue

        if r.returncode == 0:
            ok.append(str(rel))
            tail = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""
            print(f"OK       {rel}  :: {tail[:80]}", flush=True)
        else:
            failed.append(str(rel))
            err = (r.stderr or r.stdout or "").strip().splitlines()[-5:]
            print(f"FAIL({r.returncode}) {rel}", flush=True)
            for line in err:
                print(f"         {line}", flush=True)

    print()
    print(f"Summary: OK={len(ok)} TIMEOUT={len(timed_out)} FAIL={len(failed)}")
    if timed_out:
        print("\n--- TIMEOUT / likely HANG ---")
        for p in timed_out:
            print(p)
    if failed:
        print("\n--- FAIL (not timeout) ---")
        for p in failed:
            print(p)
    return 0 if not timed_out and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
