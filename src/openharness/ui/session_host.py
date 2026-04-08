"""Shared session host: single source of truth for TUI and Web clients."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from openharness.api.client import SupportsStreamingMessages
from openharness.bridge import get_bridge_manager
from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    MaxTurnsReached,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
    UserMessage,
)
from openharness.swarm.debugger import (
    LIVE_MAIN_AGENT_ID,
    SwarmDebuggerService,
    create_default_swarm_debugger_service,
)
from openharness.tasks.agent_tasks import count_agent_tasks_for_cwd, list_agent_tasks_for_cwd
from openharness.tasks.types import TaskRecord
from openharness.ui.protocol import BackendEvent, FrontendRequest, TaskSnapshot, TranscriptItem, _state_payload
from openharness.ui.runtime import RuntimeBundle, build_runtime, close_runtime, handle_line, start_runtime
from openharness.session_host_registry import set_active_session_host

log = logging.getLogger(__name__)

EmitFn = Callable[[BackendEvent], Awaitable[None]]


@dataclass(frozen=True)
class SessionHostConfig:
    """Configuration for a shared session host."""

    model: str | None = None
    base_url: str | None = None
    system_prompt: str | None = None
    api_key: str | None = None
    api_format: str | None = None
    api_client: SupportsStreamingMessages | None = None
    stream_deltas: bool = False
    debug_output: str | None = None
    restore_messages: list[dict] | None = None
    permission_mode: str | None = None
    enable_shared_web: bool = True


class SessionHost:
    """Owns one RuntimeBundle and broadcasts BackendEvents to multiple subscribers."""

    def __init__(self, config: SessionHostConfig) -> None:
        self._config = config
        self._bundle: RuntimeBundle | None = None
        self._debugger: SwarmDebuggerService | None = None
        self._subscribers: dict[str, EmitFn] = {}
        self._write_lock = asyncio.Lock()
        self._request_queue: asyncio.Queue[FrontendRequest] = asyncio.Queue()
        self._permission_requests: dict[str, asyncio.Future[bool]] = {}
        self._question_requests: dict[str, asyncio.Future[str]] = {}
        self._busy = False
        self._running = True
        self._debug_logger: Any = None
        self._last_tool_inputs: dict[str, dict] = {}
        self._transcript: list[TranscriptItem] = []
        self.selected_agent_id: str | None = None
        self._ws_url: str | None = None

    @property
    def bundle(self) -> RuntimeBundle | None:
        return self._bundle

    @property
    def debugger(self) -> SwarmDebuggerService | None:
        return self._debugger

    @property
    def ws_url(self) -> str | None:
        return self._ws_url

    def set_ws_url(self, url: str | None) -> None:
        self._ws_url = url

    def add_subscriber(self, subscriber_id: str, emit_fn: EmitFn) -> Callable[[], None]:
        """Register a broadcast subscriber. Returns a remove callback."""

        self._subscribers[subscriber_id] = emit_fn

        def remove() -> None:
            self._subscribers.pop(subscriber_id, None)

        return remove

    async def enqueue_request(self, request: FrontendRequest) -> None:
        await self._request_queue.put(request)

    def snapshot_transcript(self) -> list[TranscriptItem]:
        return list(self._transcript)

    async def start(self) -> None:
        if self._config.debug_output:
            from openharness.debug.logger import DebugLogger

            self._debug_logger = DebugLogger(self._config.debug_output)

        swarm_tool_metadata = None
        if not os.environ.get("OPENHARNESS_SWARM_AGENT_ID"):
            swarm_tool_metadata = {
                "swarm_agent_id": LIVE_MAIN_AGENT_ID,
                "swarm_root_agent_id": LIVE_MAIN_AGENT_ID,
                "swarm_lineage_path": (LIVE_MAIN_AGENT_ID,),
            }
        self._bundle = await build_runtime(
            model=self._config.model,
            base_url=self._config.base_url,
            system_prompt=self._config.system_prompt,
            api_key=self._config.api_key,
            api_format=self._config.api_format,
            api_client=self._config.api_client,
            restore_messages=self._config.restore_messages,
            permission_prompt=self._ask_permission,
            ask_user_prompt=self._ask_question,
            permission_mode=self._config.permission_mode,
            swarm_tool_metadata=swarm_tool_metadata,
        )
        assert self._bundle is not None
        self._debugger = create_default_swarm_debugger_service(
            cwd=self._bundle.cwd,
            session_host=self,
        )
        await start_runtime(self._bundle)
        agent_rows, agent_total = self._agent_tasks_for_ui()
        await self.emit(
            BackendEvent.ready(
                self._bundle.app_state.get(),
                agent_rows,
                [f"/{command.name}" for command in self._bundle.commands.list_commands()],
                agent_tasks_total=agent_total,
            )
        )
        await self.emit(self._status_snapshot())
        set_active_session_host(self)

    async def set_selected_agent_id(self, agent_id: str | None) -> None:
        """Update shared selected agent and broadcast (slash commands + Web)."""
        self.selected_agent_id = (agent_id or "").strip() or None
        await self.emit(
            BackendEvent(
                type="selected_agent_changed",
                selected_agent_id=self.selected_agent_id,
            )
        )
        await self._emit_topology_snapshot()

    async def run_request_loop(self) -> int:
        """Process queued requests until shutdown."""
        try:
            while self._running:
                request = await self._request_queue.get()
                if request.type == "shutdown":
                    await self.emit(BackendEvent(type="shutdown"))
                    break
                if request.type in ("permission_response", "question_response"):
                    continue
                if request.type == "list_sessions":
                    await self._handle_list_sessions()
                    continue
                if request.type == "set_selected_agent":
                    await self._handle_set_selected_agent(request)
                    continue
                if request.type == "debugger_command":
                    await self._handle_debugger_command(request)
                    continue
                if request.type != "submit_line":
                    await self.emit(
                        BackendEvent(type="error", message=f"Unknown request type: {request.type}"),
                        target_subscriber=request.client_id or "stdio",
                    )
                    continue
                client_id = request.client_id or "stdio"
                if self._busy:
                    await self.emit(
                        BackendEvent(type="error", message="Session is busy"),
                        target_subscriber=client_id,
                    )
                    continue
                line = (request.line or "").strip()
                if not line:
                    continue
                self._busy = True
                await self.emit(
                    BackendEvent(type="busy_changed", busy=True, active_client_id=client_id),
                )
                try:
                    should_continue = await self._process_line(line)
                finally:
                    self._busy = False
                    await self.emit(
                        BackendEvent(type="busy_changed", busy=False, active_client_id=None),
                    )
                if not should_continue:
                    await self.emit(BackendEvent(type="shutdown"))
                    break
        finally:
            set_active_session_host(None)
            if self._bundle is not None:
                await self._shutdown_owned_persistent_agents()
                await close_runtime(self._bundle)
        return 0

    async def close_debug_logger(self) -> None:
        if self._debug_logger is not None:
            await self._debug_logger.close()

    def _agent_tasks_for_ui(self) -> tuple[list[TaskRecord], int]:
        """Running delegated agent tasks for this cwd (status bar + live session summaries)."""
        assert self._bundle is not None
        cwd = self._bundle.cwd
        total = count_agent_tasks_for_cwd(cwd=cwd, running_only=True)
        rows = list_agent_tasks_for_cwd(cwd=cwd, running_only=True)
        return rows, total

    async def _shutdown_owned_persistent_agents(self) -> None:
        """Best-effort graceful shutdown for the current session's persistent swarm subtree."""
        if self._bundle is None or self._debugger is None:
            return
        try:
            snapshot = self._debugger.snapshot()
        except Exception:
            return
        nodes = (snapshot.get("tree") or {}).get("nodes") or {}
        persistent_agents = [
            (agent_id, len(node.get("lineage_path", [])))
            for agent_id, node in nodes.items()
            if agent_id != LIVE_MAIN_AGENT_ID and node.get("spawn_mode") == "persistent"
        ]
        persistent_agents.sort(key=lambda item: item[1], reverse=True)
        for agent_id, _depth in persistent_agents:
            try:
                await self._debugger.stop_agent(agent_id)
            except Exception:
                continue

    async def emit(
        self,
        event: BackendEvent,
        *,
        target_subscriber: str | None = None,
    ) -> None:
        self._buffer_transcript(event)
        async with self._write_lock:
            if target_subscriber:
                fn = self._subscribers.get(target_subscriber)
                if fn:
                    await fn(event)
                return
            for fn in list(self._subscribers.values()):
                await fn(event)

    def _buffer_transcript(self, event: BackendEvent) -> None:
        if event.type == "transcript_item" and event.item:
            self._transcript.append(event.item)
        elif event.type in ("tool_started", "tool_completed") and event.item:
            self._transcript.append(event.item)
        elif event.type == "assistant_complete" and event.item:
            self._transcript.append(event.item)
        elif event.type == "clear_transcript":
            self._transcript.clear()

    def build_session_resync_event(self) -> BackendEvent:
        """Full OH session snapshot for Web UI (same payload as session_resync)."""
        assert self._bundle is not None
        topo: dict[str, Any] | None = None
        if self._debugger is not None:
            try:
                topo = self._debugger.snapshot()
            except Exception:
                topo = None
        agent_rows, agent_total = self._agent_tasks_for_ui()
        return BackendEvent(
            type="session_resync",
            transcript=[t.model_dump() for t in self._transcript],
            state=_state_payload(self._bundle.app_state.get()),
            tasks=[TaskSnapshot.from_record(t).model_dump() for t in agent_rows],
            agent_tasks_total=agent_total,
            commands=[f"/{c.name}" for c in self._bundle.commands.list_commands()],
            mcp_servers=self._mcp_payload(),
            bridge_sessions=self._bridge_payload(),
            selected_agent_id=self.selected_agent_id,
            topology=topo,
        )

    async def emit_session_resync(self, subscriber_id: str) -> None:
        """Send full session state to one subscriber (on Web attach)."""
        await self.emit(self.build_session_resync_event(), target_subscriber=subscriber_id)

    def _mcp_payload(self) -> list[dict[str, Any]]:
        assert self._bundle is not None
        return [
            {
                "name": s.name,
                "state": s.state,
                "detail": s.detail,
                "transport": s.transport,
                "auth_configured": s.auth_configured,
                "tool_count": len(s.tools),
                "resource_count": len(s.resources),
            }
            for s in self._bundle.mcp_manager.list_statuses()
        ]

    def _bridge_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": s.session_id,
                "command": s.command,
                "cwd": s.cwd,
                "pid": s.pid,
                "status": s.status,
                "started_at": s.started_at,
                "output_path": s.output_path,
            }
            for s in get_bridge_manager().list_sessions()
        ]

    async def handle_permission_response(self, request: FrontendRequest) -> None:
        if request.request_id and request.request_id in self._permission_requests:
            future = self._permission_requests[request.request_id]
            if not future.done():
                future.set_result(bool(request.allowed))

    async def handle_question_response(self, request: FrontendRequest) -> None:
        if request.request_id and request.request_id in self._question_requests:
            future = self._question_requests[request.request_id]
            if not future.done():
                future.set_result(request.answer or "")

    async def _handle_set_selected_agent(self, request: FrontendRequest) -> None:
        raw = (request.line or "").strip()
        await self.set_selected_agent_id(raw or None)

    async def _handle_debugger_command(self, request: FrontendRequest) -> None:
        if self._debugger is None:
            await self.emit(
                BackendEvent(type="error", message="Debugger service not available"),
                target_subscriber=request.client_id or "stdio",
            )
            return
        cmd = request.debugger_command or ""
        payload = request.debugger_payload or {}
        try:
            if cmd == "pause_agent":
                ok = await self._debugger.pause_agent(str(payload["agent_id"]))
                await self.emit(BackendEvent(type="debugger_ack", debugger_result={"ok": ok}))
            elif cmd == "resume_agent":
                ok = await self._debugger.resume_agent(str(payload["agent_id"]))
                await self.emit(BackendEvent(type="debugger_ack", debugger_result={"ok": ok}))
            elif cmd == "stop_agent":
                ok = await self._debugger.stop_agent(str(payload["agent_id"]))
                await self.emit(BackendEvent(type="debugger_ack", debugger_result={"ok": ok}))
            elif cmd == "apply_context_patch":
                snap = self._debugger.apply_context_patch(
                    str(payload["agent_id"]),
                    patch=dict(payload["patch"]),
                    base_version=int(payload["base_version"]),
                )
                await self.emit(
                    BackendEvent(
                        type="debugger_ack",
                        debugger_result={"context_version": getattr(snap, "context_version", None)},
                    ),
                )
            elif cmd == "send_message":
                result = await self._debugger.send_message(
                    str(payload["agent_id"]),
                    str(payload["message"]),
                )
                await self.emit(BackendEvent(type="debugger_ack", debugger_result=result))
            else:
                await self.emit(
                    BackendEvent(type="error", message=f"Unknown debugger command: {cmd}"),
                    target_subscriber=request.client_id or "stdio",
                )
                return
        except Exception as exc:
            await self.emit(
                BackendEvent(type="error", message=str(exc)),
                target_subscriber=request.client_id or "stdio",
            )
            return
        await self._emit_topology_snapshot()

    async def _emit_topology_snapshot(self) -> None:
        if self._debugger is None:
            return
        try:
            topo = self._debugger.snapshot()
            await self.emit(
                BackendEvent(
                    type="topology_snapshot",
                    topology=topo,
                    selected_agent_id=self.selected_agent_id,
                )
            )
        except Exception as exc:
            log.debug("topology snapshot failed: %s", exc)

    async def _process_line(self, line: str) -> bool:
        assert self._bundle is not None
        await self.emit(
            BackendEvent(type="transcript_item", item=TranscriptItem(role="user", text=line))
        )
        if self._debug_logger is not None:
            await self._debug_logger(UserMessage(text=line))

        async def _print_system(message: str) -> None:
            await self.emit(
                BackendEvent(type="transcript_item", item=TranscriptItem(role="system", text=message))
            )

        async def _render_event(event: StreamEvent) -> None:
            if isinstance(event, StatusEvent):
                await self.emit(
                    BackendEvent(
                        type="transcript_item",
                        item=TranscriptItem(role="system", text=event.message),
                    )
                )
                return
            if isinstance(event, ErrorEvent):
                await self.emit(BackendEvent(type="error", message=event.message))
                return
            if isinstance(event, AssistantTextDelta):
                if self._config.stream_deltas:
                    await self.emit(BackendEvent(type="assistant_delta", message=event.text))
                if self._debug_logger is not None:
                    await self._debug_logger(event)
                return
            if isinstance(event, AssistantTurnComplete):
                await self.emit(
                    BackendEvent(
                        type="assistant_complete",
                        message=event.message.text.strip(),
                        item=TranscriptItem(role="assistant", text=event.message.text.strip()),
                        usage=event.usage.model_dump() if event.usage else None,
                    )
                )
                ar, at = self._agent_tasks_for_ui()
                await self.emit(BackendEvent.tasks_snapshot(ar, agent_tasks_total=at))
                if self._debug_logger is not None:
                    await self._debug_logger(event)
                return
            if isinstance(event, ToolExecutionStarted):
                self._last_tool_inputs[event.tool_name] = event.tool_input or {}
                await self.emit(
                    BackendEvent(
                        type="tool_started",
                        tool_name=event.tool_name,
                        tool_input=event.tool_input,
                        item=TranscriptItem(
                            role="tool",
                            text=f"{event.tool_name} {json.dumps(event.tool_input, ensure_ascii=True)}",
                            tool_name=event.tool_name,
                            tool_input=event.tool_input,
                        ),
                    )
                )
                if self._debug_logger is not None:
                    await self._debug_logger(event)
                return
            if isinstance(event, ToolExecutionCompleted):
                await self.emit(
                    BackendEvent(
                        type="tool_completed",
                        tool_name=event.tool_name,
                        output=event.output,
                        is_error=event.is_error,
                        item=TranscriptItem(
                            role="tool_result",
                            text=event.output,
                            tool_name=event.tool_name,
                            is_error=event.is_error,
                        ),
                    )
                )
                ar, at = self._agent_tasks_for_ui()
                await self.emit(BackendEvent.tasks_snapshot(ar, agent_tasks_total=at))
                await self.emit(self._status_snapshot())
                if self._debug_logger is not None:
                    await self._debug_logger(event)
                if event.tool_name in ("TodoWrite", "todo_write"):
                    tool_input = self._last_tool_inputs.get(event.tool_name, {})
                    todos = tool_input.get("todos") or tool_input.get("content") or []
                    if isinstance(todos, list) and todos:
                        lines = []
                        for item in todos:
                            if isinstance(item, dict):
                                checked = item.get("status", "") in ("done", "completed", "x", True)
                                text = item.get("content") or item.get("text") or str(item)
                                lines.append(f"- [{'x' if checked else ' '}] {text}")
                        if lines:
                            await self.emit(BackendEvent(type="todo_update", todo_markdown="\n".join(lines)))
                    else:
                        await self._emit_todo_update_from_output(event.output)
                if event.tool_name in ("set_permission_mode", "plan_mode", "enter_plan_mode", "exit_plan_mode"):
                    assert self._bundle is not None
                    new_mode = self._bundle.app_state.get().permission_mode
                    await self.emit(BackendEvent(type="plan_mode_change", plan_mode=new_mode))
                return
            if isinstance(event, MaxTurnsReached):
                await self.emit(
                    BackendEvent(
                        type="transcript_item",
                        item=TranscriptItem(
                            role="system",
                            text=(
                                f"Max turns reached ({event.max_turns}). "
                                "Use /set-max-turns to increase the limit."
                            ),
                        ),
                    )
                )
                if self._debug_logger is not None:
                    await self._debug_logger(event)
                return

        async def _clear_output() -> None:
            await self.emit(BackendEvent(type="clear_transcript"))

        should_continue = await handle_line(
            self._bundle,
            line,
            print_system=_print_system,
            render_event=_render_event,
            clear_output=_clear_output,
        )
        await self.emit(self._status_snapshot())
        ar, at = self._agent_tasks_for_ui()
        await self.emit(BackendEvent.tasks_snapshot(ar, agent_tasks_total=at))
        await self.emit(BackendEvent(type="line_complete"))
        await self._emit_topology_snapshot()
        return should_continue

    def _status_snapshot(self) -> BackendEvent:
        assert self._bundle is not None
        return BackendEvent.status_snapshot(
            state=self._bundle.app_state.get(),
            mcp_servers=self._bundle.mcp_manager.list_statuses(),
            bridge_sessions=get_bridge_manager().list_sessions(),
        )

    async def _emit_todo_update_from_output(self, output: str) -> None:
        lines = output.splitlines()
        checklist_lines = [line for line in lines if line.strip().startswith("- [")]
        if checklist_lines:
            markdown = "\n".join(checklist_lines)
            await self.emit(BackendEvent(type="todo_update", todo_markdown=markdown))

    async def _handle_list_sessions(self) -> None:
        from openharness.services.session_storage import list_session_snapshots
        import time as _time

        assert self._bundle is not None
        sessions = list_session_snapshots(self._bundle.cwd, limit=10)
        options = []
        for s in sessions:
            ts = _time.strftime("%m/%d %H:%M", _time.localtime(s["created_at"]))
            summary = s.get("summary", "")[:50] or "(no summary)"
            options.append({
                "value": s["session_id"],
                "label": f"{ts}  {s['message_count']}msg  {summary}",
            })
        await self.emit(
            BackendEvent(
                type="select_request",
                modal={"kind": "select", "title": "Resume Session", "submit_prefix": "/resume "},
                select_options=options,
            )
        )

    async def _ask_permission(self, tool_name: str, reason: str) -> bool:
        request_id = uuid4().hex
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._permission_requests[request_id] = future
        await self.emit(
            BackendEvent(
                type="modal_request",
                modal={
                    "kind": "permission",
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "reason": reason,
                },
            )
        )
        try:
            return await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            log.warning("Permission request %s timed out after 300s, denying", request_id)
            return False
        finally:
            self._permission_requests.pop(request_id, None)

    async def _ask_question(self, question: str) -> str:
        request_id = uuid4().hex
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._question_requests[request_id] = future
        await self.emit(
            BackendEvent(
                type="modal_request",
                modal={
                    "kind": "question",
                    "request_id": request_id,
                    "question": question,
                },
            )
        )
        try:
            return await future
        finally:
            self._question_requests.pop(request_id, None)


__all__ = ["SessionHost", "SessionHostConfig"]
