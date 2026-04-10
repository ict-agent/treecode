"""Deterministic handshake/status checks for current live swarm children."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from treecode.swarm.event_store import get_event_store
from treecode.swarm.topology_reader import build_projection, live_runtime_state, materialize_topology
from treecode.tasks.manager import load_persisted_task_record
from treecode.tools.base import BaseTool, ToolExecutionContext, ToolResult
from treecode.tools.send_message_tool import SendMessageTool, SendMessageToolInput
from treecode.tools.swarm_context_tool import _current_session_tree, resolve_swarm_identity


class SwarmHandshakeToolInput(BaseModel):
    """Arguments for deterministic child handshake."""

    model_config = ConfigDict(extra="forbid")

    agent_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit child agent ids. Defaults to current live direct children in this session.",
    )
    message: str | None = Field(
        default=None,
        description="Optional custom handshake text. Defaults to a deterministic parent-status request.",
    )
    wait_seconds: float = Field(
        default=10,
        ge=0,
        le=60,
        description="How long to wait before reading child responses from task logs.",
    )


class SwarmHandshakeTool(BaseTool):
    """Send a deterministic handshake to current live child agents and summarize responses."""

    name = "swarm_handshake"
    description = (
        "Send a deterministic handshake/status-check message to current live direct children in this session "
        "and summarize their latest replies. Use this instead of ad-hoc send_message + task_list loops when you "
        "want to confirm which current child agents are alive and ready."
    )
    input_model = SwarmHandshakeToolInput

    def is_read_only(self, arguments: SwarmHandshakeToolInput) -> bool:
        return bool(arguments.wait_seconds >= 0)

    async def execute(self, arguments: SwarmHandshakeToolInput, context: ToolExecutionContext) -> ToolResult:
        resolved = resolve_swarm_identity(context)
        if resolved is None:
            return ToolResult(output="No active swarm context for deterministic handshake.", is_error=True)
        current_agent_id, parent_agent_id, root_agent_id, lineage_path = resolved
        del parent_agent_id, root_agent_id, lineage_path

        targets = arguments.agent_ids or self._current_live_children(context, current_agent_id)
        if not targets:
            return ToolResult(output=f"No current live direct children found for {current_agent_id}.")

        message = arguments.message or (
            f"你好！我是你的父节点 {current_agent_id}。请确认你的 agent id、当前状态，以及是否 ready 继续协作。"
        )

        send_tool = SendMessageTool()
        for agent_id in targets:
            result = await send_tool.execute(
                SendMessageToolInput(task_id=agent_id, message=message),
                context,
            )
            if result.is_error:
                return result

        if arguments.wait_seconds > 0:
            await asyncio.sleep(arguments.wait_seconds)

        lines = [f"Deterministic handshake from {current_agent_id} to {len(targets)} child agent(s):"]
        for agent_id in targets:
            task_id = self._latest_task_id_for_agent(agent_id)
            reply = ""
            idle = False
            if task_id is not None:
                task = load_persisted_task_record(task_id)
                if task is not None and Path(task.output_file).exists():
                    raw = Path(task.output_file).read_text(encoding="utf-8", errors="replace")
                    reply = _latest_assistant_reply(raw)
                    idle = "[status] idle" in raw or "(idle, waiting for next message)" in raw
            status = "idle" if idle else "reply pending"
            lines.append(f"- {agent_id}: {status}" + (f" — {reply}" if reply else ""))
        return ToolResult(output="\n".join(lines))

    def _current_live_children(self, context: ToolExecutionContext, current_agent_id: str) -> list[str]:
        events = get_event_store().all_events()
        topology = materialize_topology(
            build_projection(events),
            view="live",
            runtime_state_provider=live_runtime_state,
        )
        summary = topology.lookup(current_agent_id)
        if summary is not None:
            return list(summary["children"])
        if current_agent_id == "main@default":
            current_tree = _current_session_tree(
                events=events,
                base_tree=topology.tree,
                runtime_state=topology.runtime_state,
                current_agent_id=current_agent_id,
                current_parent_agent_id=None,
                current_root_agent_id=current_agent_id,
                current_lineage_path=(current_agent_id,),
                current_session_id=str(context.metadata.get("session_id") or current_agent_id),
            )
            node = current_tree["nodes"].get(current_agent_id, {})
            return list(node.get("children", []))
        return []

    @staticmethod
    def _latest_task_id_for_agent(agent_id: str) -> str | None:
        for event in reversed(get_event_store().all_events()):
            if event.event_type == "agent_spawned" and event.agent_id == agent_id:
                task_id = event.payload.get("task_id")
                if task_id is not None:
                    return str(task_id)
        return None


def _latest_assistant_reply(raw: str) -> str:
    latest = ""
    for line in raw.splitlines():
        payload = line.strip()
        if payload.startswith("TCJSON:"):
            payload = payload[7:]
        try:
            obj = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "assistant_complete":
            latest = str(obj.get("message", "")).strip() or latest
        elif obj.get("type") == "transcript_item":
            item = obj.get("item", {})
            if isinstance(item, dict) and item.get("role") == "assistant":
                latest = str(item.get("text", "")).strip() or latest
    if len(latest) > 200:
        latest = latest[:200] + "…"
    return latest
