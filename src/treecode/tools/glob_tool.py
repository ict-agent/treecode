"""Filesystem globbing tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from treecode.tools.base import BaseTool, ToolExecutionContext, ToolResult

# Hard cap on paths collected before sort/limit — avoids OOM and minutes-long walks on ** patterns.
_MAX_RAW_MATCHES = 25_000


class GlobToolInput(BaseModel):
    """Arguments for the glob tool."""

    pattern: str = Field(description="Glob pattern relative to the working directory")
    root: str | None = Field(default=None, description="Optional search root")
    limit: int = Field(default=200, ge=1, le=5000)


class GlobTool(BaseTool):
    """List files matching a glob pattern."""

    name = "glob"
    description = "List files matching a glob pattern."
    input_model = GlobToolInput

    def is_read_only(self, arguments: GlobToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: GlobToolInput, context: ToolExecutionContext) -> ToolResult:
        # Path.glob() is synchronous and can walk huge trees; run off the event loop so the TUI
        # and agent loop stay responsive (see glob_tool / asyncio blocking).
        return await asyncio.to_thread(
            _glob_sync,
            context.cwd,
            arguments.pattern,
            arguments.root,
            arguments.limit,
        )


def _glob_sync(cwd: Path, pattern: str, root_arg: str | None, limit: int) -> ToolResult:
    root = _resolve_path(cwd, root_arg) if root_arg else cwd
    rels: list[str] = []
    truncated = False
    try:
        for path in root.glob(pattern):
            try:
                rels.append(str(path.relative_to(root)))
            except ValueError:
                continue
            if len(rels) >= _MAX_RAW_MATCHES:
                truncated = True
                break
    except OSError as exc:
        return ToolResult(output=f"glob failed: {exc}", is_error=True)

    if not rels:
        return ToolResult(output="(no matches)")
    rels.sort()
    lines = rels[:limit]
    body = "\n".join(lines)
    if truncated or len(rels) > limit:
        extra = []
        if truncated:
            extra.append(
                f"(stopped after {_MAX_RAW_MATCHES} matches; use a narrower pattern or set root)"
            )
        if len(rels) > limit and not truncated:
            extra.append(f"(showing first {limit} of {len(rels)} matches)")
        body = body + "\n" + " ".join(extra)
    return ToolResult(output=body)


def _resolve_path(base: Path, candidate: str | None) -> Path:
    path = Path(candidate or ".").expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()
