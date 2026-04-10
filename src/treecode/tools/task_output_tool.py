"""Tool for reading task output."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from treecode.tasks.manager import get_task_manager
from treecode.tools.base import BaseTool, ToolExecutionContext, ToolResult


def _get_output_format() -> str:
    """Read swarm.output_format from settings. Returns 'summary' or 'raw'."""
    try:
        from treecode.config.settings import load_settings
        return load_settings().swarm.output_format
    except Exception:
        return "summary"


def _summarize_tcjson(raw: str) -> str:
    """Extract meaningful events from TCJSON log, discarding snapshots and noise.

    Keeps: tool calls, tool results (truncated), assistant messages, errors.
    Drops: ready, state_snapshot, tasks_snapshot, line_complete.
    """
    lines: list[str] = []
    for raw_line in raw.splitlines():
        payload = raw_line.strip()
        if payload.startswith("TCJSON:"):
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

    Stream-json is already cleaner than TCJSON — no snapshots, no ready.
    While the task is still running only assistant_delta events may be present;
    in that case we concatenate the deltas as a partial output so the caller
    gets something useful instead of "(no meaningful output)".
    """
    lines: list[str] = []
    delta_parts: list[str] = []
    has_complete = False

    for raw_line in raw.splitlines():
        payload = raw_line.strip()
        if not payload:
            continue
        try:
            obj = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            # Skip truncated partial lines silently (common when log is mid-write)
            continue

        event_type = obj.get("type", "")

        if event_type == "assistant_delta":
            delta_parts.append(obj.get("text", ""))
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
                has_complete = True
                delta_parts.clear()  # deltas are now superseded by the complete event

        elif event_type == "system":
            lines.append(f"[system] {obj.get('message', '')}")

        elif event_type == "max_turns_reached":
            lines.append(f"[max_turns] reached {obj.get('max_turns', '?')}")

        else:
            lines.append(f"[{event_type}] {json.dumps(obj, ensure_ascii=False)[:200]}")

    # If no assistant_complete appeared yet (task still running), show partial delta text
    if not has_complete and delta_parts:
        partial = "".join(delta_parts).strip()
        if partial:
            lines.append(f"[partial — task still running] {partial[:1000]}")

    return "\n".join(lines) if lines else "(no output yet — task may still be running)"


def summarize_task_output(raw: str) -> str:
    """Auto-detect format and summarize task output.

    The log may be read from the tail (max_bytes), so the first line can be a
    truncated partial JSON string. Scan the first non-empty lines to detect format.
    """
    if "TCJSON:" in raw:
        return _summarize_tcjson(raw)
    # Scan up to 10 lines looking for a complete JSON object to confirm stream-json format
    for line in raw.splitlines()[:10]:
        line = line.strip()
        if line.startswith("{") and '"type"' in line:
            return _summarize_stream_json(raw)
    return raw


class TaskOutputToolInput(BaseModel):
    """Arguments for task output retrieval."""

    task_id: str = Field(description="Task identifier")
    max_bytes: int = Field(
        default=12000,
        ge=1,
        le=100000,
        description=(
            "Maximum bytes to read from the tail of the log. Only applies in raw=true mode. "
            "In summary mode the full log is scanned so this parameter is ignored."
        ),
    )
    raw: bool = Field(
        default=False,
        description=(
            "Return raw output without filtering. "
            "Default false (strongly recommended): scans the full log and extracts "
            "only tool calls, tool results, and assistant messages — readable and compact. "
            "While the task is running, partial output is shown. "
            "Set raw=true ONLY for debugging the harness internals; "
            "the raw log contains thousands of streaming delta fragments that are hard to read."
        ),
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
        use_raw = arguments.raw or _get_output_format() == "raw"

        try:
            if use_raw:
                # Raw mode: tail-read up to max_bytes so caller can control window size
                output = get_task_manager().read_task_output(
                    arguments.task_id, max_bytes=arguments.max_bytes
                )
            else:
                # Summary mode: scan the full log so no events are missed due to tail truncation.
                # The summariser compresses the output heavily, so reading more is fine.
                output = get_task_manager().read_task_output(
                    arguments.task_id, max_bytes=500_000
                )
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)

        if not output:
            return ToolResult(output="(no output)")

        if use_raw:
            return ToolResult(output=output)

        return ToolResult(output=summarize_task_output(output))
