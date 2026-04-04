"""Tool for reading task output."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from openharness.tasks.manager import get_task_manager
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


def _get_output_format() -> str:
    """Read swarm.output_format from settings. Returns 'summary' or 'raw'."""
    try:
        from openharness.config.settings import load_settings
        return load_settings().swarm.output_format
    except Exception:
        return "summary"


def _summarize_ohjson(raw: str) -> str:
    """Extract meaningful events from OHJSON log, discarding snapshots and noise.

    Keeps: tool calls, tool results (truncated), assistant messages, errors.
    Drops: ready, state_snapshot, tasks_snapshot, line_complete.
    """
    lines: list[str] = []
    for raw_line in raw.splitlines():
        payload = raw_line.strip()
        if payload.startswith("OHJSON:"):
            payload = payload[7:]
        try:
            obj = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            if payload:
                lines.append(payload)
            continue

        event_type = obj.get("type", "")

        if event_type in ("ready", "state_snapshot", "tasks_snapshot"):
            continue

        if event_type == "tool_started":
            tool = obj.get("tool_name", "")
            inp = obj.get("tool_input", {})
            inp_str = json.dumps(inp, ensure_ascii=False) if inp else ""
            if len(inp_str) > 200:
                inp_str = inp_str[:200] + "..."
            lines.append(f"[tool_call] {tool} {inp_str}")

        elif event_type == "tool_completed":
            tool = obj.get("tool_name", "")
            output = obj.get("output", "")
            is_error = obj.get("is_error", False)
            if len(output) > 500:
                output = output[:500] + "...(truncated)"
            prefix = "[tool_error]" if is_error else "[tool_result]"
            lines.append(f"{prefix} {tool}: {output}")

        elif event_type == "assistant_complete":
            msg = obj.get("message", "")
            if msg:
                lines.append(f"[assistant] {msg}")

        elif event_type == "transcript_item":
            item = obj.get("item", {})
            role = item.get("role", "")
            text = item.get("text", "")
            if role == "user" and text:
                lines.append(f"[user] {text}")

        elif event_type == "line_complete":
            lines.append("[status] agent finished processing prompt (idle, waiting for next message)")

        elif event_type == "error":
            lines.append(f"[error] {obj.get('message', str(obj))}")

        else:
            if event_type.startswith("assistant_"):
                continue
            lines.append(f"[{event_type}] {json.dumps(obj, ensure_ascii=False)[:200]}")

    return "\n".join(lines) if lines else "(no meaningful output)"


def _summarize_stream_json(raw: str) -> str:
    """Extract meaningful events from stream-json output (from -p mode).

    Stream-json is already cleaner than OHJSON — no snapshots, no ready.
    """
    lines: list[str] = []
    for raw_line in raw.splitlines():
        payload = raw_line.strip()
        if not payload:
            continue
        try:
            obj = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            if payload:
                lines.append(payload)
            continue

        event_type = obj.get("type", "")

        if event_type == "assistant_delta":
            continue

        if event_type == "tool_started":
            tool = obj.get("tool_name", "")
            inp_str = json.dumps(obj.get("tool_input", {}), ensure_ascii=False)
            if len(inp_str) > 200:
                inp_str = inp_str[:200] + "..."
            lines.append(f"[tool_call] {tool} {inp_str}")

        elif event_type == "tool_completed":
            tool = obj.get("tool_name", "")
            output = obj.get("output", "")
            is_error = obj.get("is_error", False)
            if len(output) > 500:
                output = output[:500] + "...(truncated)"
            prefix = "[tool_error]" if is_error else "[tool_result]"
            lines.append(f"{prefix} {tool}: {output}")

        elif event_type == "assistant_complete":
            text = obj.get("text", "")
            if text:
                lines.append(f"[assistant] {text}")

        elif event_type == "system":
            lines.append(f"[system] {obj.get('message', '')}")

        elif event_type == "max_turns_reached":
            lines.append(f"[max_turns] reached {obj.get('max_turns', '?')}")

        else:
            lines.append(f"[{event_type}] {json.dumps(obj, ensure_ascii=False)[:200]}")

    return "\n".join(lines) if lines else "(no meaningful output)"


def summarize_task_output(raw: str) -> str:
    """Auto-detect format and summarize task output."""
    if "OHJSON:" in raw:
        return _summarize_ohjson(raw)
    if raw.lstrip().startswith("{"):
        return _summarize_stream_json(raw)
    return raw


class TaskOutputToolInput(BaseModel):
    """Arguments for task output retrieval."""

    task_id: str = Field(description="Task identifier")
    max_bytes: int = Field(default=12000, ge=1, le=100000)
    raw: bool = Field(
        default=False,
        description="Return raw output without filtering. Default false returns a summarized view.",
    )


class TaskOutputTool(BaseTool):
    """Read the output of a background task."""

    name = "task_output"
    description = "Read the output log for a background task. Returns a summarized view by default; set raw=true for full output."
    input_model = TaskOutputToolInput

    def is_read_only(self, arguments: TaskOutputToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: TaskOutputToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            output = get_task_manager().read_task_output(arguments.task_id, max_bytes=arguments.max_bytes)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)

        if not output:
            return ToolResult(output="(no output)")

        use_raw = arguments.raw or _get_output_format() == "raw"
        if use_raw:
            return ToolResult(output=output)

        return ToolResult(output=summarize_task_output(output))
