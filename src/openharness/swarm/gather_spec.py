"""Project-local recursive gather spec loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from openharness.config.paths import get_project_config_dir

GatherOrdering = Literal["topology", "name"]
GatherReturnMode = Literal["tree"]


@dataclass(frozen=True)
class GatherSpec:
    """Parsed gather spec loaded from a project-local markdown file."""

    name: str
    description: str
    version: int
    allow_none: bool
    timeout_seconds: float
    ordering: GatherOrdering
    return_mode: GatherReturnMode
    instructions: str
    path: Path


def get_project_gather_dir(cwd: str | Path) -> Path:
    """Return the project-local gather spec directory."""

    path = get_project_config_dir(cwd) / "gather"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_gather_spec(name: str, cwd: str | Path) -> GatherSpec | None:
    """Load one project-local gather spec by file stem or explicit name."""

    target = get_project_gather_dir(cwd) / f"{name}.md"
    if not target.exists():
        return None

    frontmatter, body = _parse_markdown_frontmatter(target.read_text(encoding="utf-8"))
    spec_name = str(frontmatter.get("name", "")).strip() or target.stem
    description = str(frontmatter.get("description", "")).strip() or f"Gather spec: {spec_name}"
    version = _parse_positive_int(frontmatter.get("version")) or 1
    allow_none = _parse_bool(frontmatter.get("allow_none"))
    timeout_seconds = _parse_positive_float(frontmatter.get("timeout_seconds")) or 30.0
    ordering = _parse_ordering(frontmatter.get("ordering"))
    return_mode = _parse_return_mode(frontmatter.get("return_mode"))

    return GatherSpec(
        name=spec_name,
        description=description,
        version=version,
        allow_none=allow_none,
        timeout_seconds=timeout_seconds,
        ordering=ordering,
        return_mode=return_mode,
        instructions=body,
        path=target,
    )


def _parse_markdown_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and return ``(frontmatter, body)``."""

    frontmatter: dict[str, Any] = {}
    body = content.strip()
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return frontmatter, body

    end_index: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break
    if end_index is None:
        return frontmatter, body

    fm_text = "\n".join(lines[1:end_index])
    try:
        parsed = yaml.safe_load(fm_text)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except yaml.YAMLError:
        for fm_line in lines[1:end_index]:
            if ":" not in fm_line:
                continue
            key, _, value = fm_line.partition(":")
            frontmatter[key.strip()] = value.strip().strip("'\"")

    body = "\n".join(lines[end_index + 1 :]).strip()
    return frontmatter, body


def _parse_positive_int(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _parse_positive_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _parse_ordering(raw: Any) -> GatherOrdering:
    if raw == "name":
        return "name"
    return "topology"


def _parse_return_mode(raw: Any) -> GatherReturnMode:
    del raw
    return "tree"
