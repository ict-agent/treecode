"""Helpers for `/execute` command input files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutableInputLine:
    """One user input line loaded from an execute script."""

    line_no: int
    raw_text: str
    input_text: str


def load_execute_lines(path: str | Path, *, cwd: str | Path) -> list[ExecutableInputLine]:
    """Load executable input lines from *path* relative to *cwd*."""

    resolved = _resolve_execute_path(path, cwd=cwd)
    if not resolved.exists():
        raise FileNotFoundError(f"Execute script not found: {resolved}")

    lines: list[ExecutableInputLine] = []
    for line_no, raw_line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(
            ExecutableInputLine(
                line_no=line_no,
                raw_text=stripped,
                input_text=stripped,
            )
        )
    return lines


def _resolve_execute_path(path: str | Path, *, cwd: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(cwd) / candidate
