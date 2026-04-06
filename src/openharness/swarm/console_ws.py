"""WebSocket transport for the multi-agent console."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve

from openharness.swarm.console_protocol import ConsoleClientMessage, ConsoleServerMessage
from openharness.swarm.debugger import SwarmDebuggerService


class SwarmConsoleWsServer:
    """Expose swarm debugger operations over a WebSocket transport."""

    def __init__(self, *, service: SwarmDebuggerService, host: str = "127.0.0.1", port: int = 0) -> None:
        self._service = service
        self._host = host
        self._port = port
        self._server: Server | None = None
        self._clients: set[ServerConnection] = set()
        self._watcher_task: asyncio.Task[None] | None = None
        self._last_change_token: tuple[str, int, str | None] | None = None

    @property
    def ws_url(self) -> str:
        """Return the WebSocket URL after the server has started."""
        assert self._server is not None
        sock = self._server.sockets[0]
        host, port = sock.getsockname()[:2]
        return f"ws://{host}:{port}"

    async def start(self) -> None:
        """Start accepting WebSocket connections."""
        self._server = await serve(self._handle_connection, self._host, self._port)
        self._last_change_token = self._service.change_token()
        self._watcher_task = asyncio.create_task(self._watch_for_changes())

    async def stop(self) -> None:
        """Stop the server and close existing client connections."""
        for client in list(self._clients):
            await client.close()
        self._clients.clear()
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task
            self._watcher_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        self._clients.add(websocket)
        try:
            await self._send_snapshot(websocket)
            async for raw in websocket:
                message = ConsoleClientMessage.model_validate_json(raw)
                await self._dispatch(websocket, message)
        finally:
            self._clients.discard(websocket)

    async def _dispatch(self, websocket: ServerConnection, message: ConsoleClientMessage) -> None:
        if message.type == "subscribe":
            await self._send_snapshot(websocket)
            return

        if message.type != "command" or not message.command:
            await websocket.send(
                ConsoleServerMessage(type="error", message="Invalid console command").model_dump_json()
            )
            return

        try:
            message_type, handler_result, should_broadcast = await self._handle_command(message.command, message.payload)
        except Exception as exc:
            await websocket.send(
                ConsoleServerMessage(type="error", message=str(exc)).model_dump_json()
            )
            return
        await websocket.send(
            ConsoleServerMessage(type=message_type, payload=handler_result if isinstance(handler_result, dict) else {}).model_dump_json()
        )
        if should_broadcast:
            await self._broadcast_snapshot()

    async def _handle_command(self, command: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any], bool]:
        if command == "run_scenario":
            return "ack", self._service.run_scenario(str(payload["name"])), True
        if command == "set_active_source":
            result = self._service.set_active_source(str(payload["source"]))
            if result["active_source"] == "live":
                await self._service.maybe_ensure_live_main()
            return "ack", result, True
        if command == "agent_action":
            return "ack", await self._service.run_agent_action(
                agent_id=str(payload["agent_id"]),
                action=str(payload["action"]),
                params=dict(payload.get("params", {})),
            ), True
        if command == "resolve_approval":
            return "ack", await self._service.resolve_approval(
                str(payload["correlation_id"]),
                status=str(payload.get("status", "approved")),
            ), True
        if command == "send_message":
            return "ack", await self._service.send_message(
                str(payload["agent_id"]),
                str(payload["message"]),
            ), True
        if command == "pause_agent":
            return "ack", {"ok": await self._service.pause_agent(str(payload["agent_id"]))}, True
        if command == "resume_agent":
            return "ack", {"ok": await self._service.resume_agent(str(payload["agent_id"]))}, True
        if command == "stop_agent":
            return "ack", {"ok": await self._service.stop_agent(str(payload["agent_id"]))}, True
        if command == "list_scenarios":
            return "ack", {"scenarios": list(self._service.list_scenarios())}, False
        if command == "compare_runs":
            return "compare_result", self._service.compare_runs(
                str(payload["left_run_id"]),
                str(payload["right_run_id"]),
            ), False
        if command == "list_archives":
            return "archives", {"archives": self._service.list_archives()}, False
        if command == "archive_current_run":
            return "ack", self._service.archive_current_run(label=str(payload["label"])), True
        if command == "spawn_agent":
            return "ack", await self._service.spawn_agent(
                agent_id=str(payload["agent_id"]),
                prompt=str(payload["prompt"]),
                parent_agent_id=payload.get("parent_agent_id") and str(payload["parent_agent_id"]) or None,
                mode=str(payload.get("mode", "synthetic")),
            ), True
        if command == "reparent_agent":
            return "ack", self._service.reparent_agent(
                str(payload["agent_id"]),
                payload.get("new_parent_agent_id") and str(payload["new_parent_agent_id"]) or None,
            ), True
        if command == "remove_agent":
            return "ack", await self._service.remove_agent(str(payload["agent_id"])), True
        if command == "apply_context_patch":
            snapshot = self._service.apply_context_patch(
                str(payload["agent_id"]),
                patch=dict(payload["patch"]),
                base_version=int(payload["base_version"]),
            )
            return "ack", snapshot.to_dict(), True
        if command == "get_snapshot":
            await self._service.maybe_ensure_live_main()
            return "snapshot", self._service.snapshot(), False
        raise ValueError(f"Unknown console command: {command}")

    async def _broadcast_snapshot(self) -> None:
        if not self._clients:
            return
        await self._service.maybe_ensure_live_main()
        payload = ConsoleServerMessage(type="snapshot", payload=self._service.snapshot()).model_dump_json()
        self._last_change_token = self._service.change_token()
        await asyncio.gather(*(client.send(payload) for client in list(self._clients)))

    async def _send_snapshot(self, websocket: ServerConnection) -> None:
        await self._service.maybe_ensure_live_main()
        self._last_change_token = self._service.change_token()
        await websocket.send(
            ConsoleServerMessage(type="snapshot", payload=self._service.snapshot()).model_dump_json()
        )

    async def _watch_for_changes(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.2)
                if not self._clients:
                    continue
                token = self._service.change_token()
                if token != self._last_change_token:
                    await self._broadcast_snapshot()
        except asyncio.CancelledError:
            return
