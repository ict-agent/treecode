"""Structured protocol models for the React TUI backend."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from openharness.state.app_state import AppState
from openharness.bridge.manager import BridgeSessionRecord
from openharness.mcp.types import McpConnectionStatus
from openharness.tasks.types import TaskRecord


class FrontendRequest(BaseModel):
    """One request sent from the React frontend to the Python backend."""

    type: Literal[
        "submit_line",
        "permission_response",
        "question_response",
        "list_sessions",
        "shutdown",
        "set_selected_agent",
        "debugger_command",
    ]
    line: str | None = None
    """Optional client id for targeted errors (e.g. ``web-<uuid>``). ``stdio`` for terminal."""
    client_id: str | None = None
    request_id: str | None = None
    allowed: bool | None = None
    answer: str | None = None
    debugger_command: str | None = None
    debugger_payload: dict[str, Any] | None = None


class TranscriptItem(BaseModel):
    """One transcript row rendered by the frontend."""

    role: Literal["system", "user", "assistant", "tool", "tool_result", "log"]
    text: str
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    is_error: bool | None = None


class TaskSnapshot(BaseModel):
    """UI-safe task representation."""

    id: str
    type: str
    status: str
    description: str
    metadata: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: TaskRecord) -> "TaskSnapshot":
        return cls(
            id=record.id,
            type=record.type,
            status=record.status,
            description=record.description,
            metadata=dict(record.metadata),
        )


class BackendEvent(BaseModel):
    """One event sent from the Python backend to the React frontend."""

    type: Literal[
        "ready",
        "state_snapshot",
        "tasks_snapshot",
        "transcript_item",
        "assistant_delta",
        "assistant_complete",
        "line_complete",
        "tool_started",
        "tool_completed",
        "clear_transcript",
        "modal_request",
        "select_request",
        "todo_update",
        "plan_mode_change",
        "swarm_status",
        "session_resync",
        "busy_changed",
        "selected_agent_changed",
        "topology_snapshot",
        "debugger_ack",
        "shared_session_ready",
        "error",
        "shutdown",
    ]
    select_options: list[dict[str, Any]] | None = None
    message: str | None = None
    item: TranscriptItem | None = None
    state: dict[str, Any] | None = None
    tasks: list[TaskSnapshot] | None = None
    mcp_servers: list[dict[str, Any]] | None = None
    bridge_sessions: list[dict[str, Any]] | None = None
    commands: list[str] | None = None
    modal: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    output: str | None = None
    is_error: bool | None = None
    usage: dict[str, int] | None = None
    todo_markdown: str | None = None
    plan_mode: str | None = None
    swarm_teammates: list[dict[str, Any]] | None = None
    swarm_notifications: list[dict[str, Any]] | None = None
    transcript: list[dict[str, Any]] | None = None
    topology: dict[str, Any] | None = None
    selected_agent_id: str | None = None
    busy: bool | None = None
    active_client_id: str | None = None
    debugger_result: dict[str, Any] | None = None
    ws_url: str | None = None
    #: Uncapped count of delegated agent tasks in this session cwd (matches ``/agents all`` scope).
    agent_tasks_total: int | None = None

    @classmethod
    def ready(
        cls,
        state: AppState,
        tasks: list[TaskRecord],
        commands: list[str],
        *,
        agent_tasks_total: int | None = None,
    ) -> "BackendEvent":
        return cls(
            type="ready",
            state=_state_payload(state),
            tasks=[TaskSnapshot.from_record(task) for task in tasks],
            mcp_servers=[],
            bridge_sessions=[],
            commands=commands,
            agent_tasks_total=agent_tasks_total,
        )

    @classmethod
    def state_snapshot(cls, state: AppState) -> "BackendEvent":
        return cls(type="state_snapshot", state=_state_payload(state))

    @classmethod
    def tasks_snapshot(
        cls,
        tasks: list[TaskRecord],
        *,
        agent_tasks_total: int | None = None,
    ) -> "BackendEvent":
        return cls(
            type="tasks_snapshot",
            tasks=[TaskSnapshot.from_record(task) for task in tasks],
            agent_tasks_total=agent_tasks_total,
        )

    @classmethod
    def status_snapshot(
        cls,
        *,
        state: AppState,
        mcp_servers: list[McpConnectionStatus],
        bridge_sessions: list[BridgeSessionRecord],
    ) -> "BackendEvent":
        return cls(
            type="state_snapshot",
            state=_state_payload(state),
            mcp_servers=[
                {
                    "name": server.name,
                    "state": server.state,
                    "detail": server.detail,
                    "transport": server.transport,
                    "auth_configured": server.auth_configured,
                    "tool_count": len(server.tools),
                    "resource_count": len(server.resources),
                }
                for server in mcp_servers
            ],
            bridge_sessions=[
                {
                    "session_id": session.session_id,
                    "command": session.command,
                    "cwd": session.cwd,
                    "pid": session.pid,
                    "status": session.status,
                    "started_at": session.started_at,
                    "output_path": session.output_path,
                }
                for session in bridge_sessions
            ],
        )


def _state_payload(state: AppState) -> dict[str, Any]:
    return {
        "model": state.model,
        "cwd": state.cwd,
        "provider": state.provider,
        "auth_status": state.auth_status,
        "base_url": state.base_url,
        "permission_mode": _format_permission_mode(state.permission_mode),
        "theme": state.theme,
        "vim_enabled": state.vim_enabled,
        "voice_enabled": state.voice_enabled,
        "voice_available": state.voice_available,
        "voice_reason": state.voice_reason,
        "fast_mode": state.fast_mode,
        "effort": state.effort,
        "passes": state.passes,
        "mcp_connected": state.mcp_connected,
        "mcp_failed": state.mcp_failed,
        "bridge_sessions": state.bridge_sessions,
        "output_style": state.output_style,
        "keybindings": dict(state.keybindings),
    }


_MODE_LABELS = {
    "default": "Default",
    "plan": "Plan Mode",
    "full_auto": "Auto",
    "PermissionMode.DEFAULT": "Default",
    "PermissionMode.PLAN": "Plan Mode",
    "PermissionMode.FULL_AUTO": "Auto",
}


def _format_permission_mode(raw: str) -> str:
    """Convert raw permission mode to human-readable label."""
    return _MODE_LABELS.get(raw, raw)


__all__ = [
    "BackendEvent",
    "FrontendRequest",
    "TaskSnapshot",
    "TranscriptItem",
    "_state_payload",
]
