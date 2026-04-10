"""REPL input history ring on disk — same file as the Ink TUI (``repl_input_history.jsonl``)."""

from __future__ import annotations

import json
from pathlib import Path

from treecode.config.paths import get_data_dir

REPL_INPUT_HISTORY_MAX = 1000


def repl_input_history_path() -> Path:
    return get_data_dir() / "repl_input_history.jsonl"


def load_repl_input_history_lines() -> list[str]:
    """Oldest first, newest last; at most REPL_INPUT_HISTORY_MAX entries."""
    p = repl_input_history_path()
    if not p.is_file():
        return []
    lines: list[str] = []
    try:
        raw = p.read_text(encoding="utf8")
    except OSError:
        return []
    for row in raw.split("\n"):
        row = row.strip()
        if not row:
            continue
        try:
            o = json.loads(row)
            if isinstance(o, dict) and isinstance(o.get("line"), str):
                lines.append(o["line"])
        except (json.JSONDecodeError, TypeError):
            continue
    return lines[-REPL_INPUT_HISTORY_MAX:]


def save_repl_input_history_lines(entries: list[str]) -> None:
    trimmed = entries[-REPL_INPUT_HISTORY_MAX:]
    p = repl_input_history_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(json.dumps({"line": line}) for line in trimmed)
        if trimmed:
            body += "\n"
        p.write_text(body, encoding="utf8")
    except OSError:
        pass


def append_repl_input_history_line(line: str) -> list[str]:
    """Append one submitted line, persist, return the full ring."""
    t = line.strip()
    if not t:
        return load_repl_input_history_lines()
    prev = load_repl_input_history_lines()
    nxt = (prev + [t])[-REPL_INPUT_HISTORY_MAX:]
    save_repl_input_history_lines(nxt)
    return nxt
