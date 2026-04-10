"""JSON-lines backend host for the React terminal frontend (stdio transport to SessionHost)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from typing import Any

from urllib.parse import quote

from treecode.api.client import SupportsStreamingMessages
from treecode.ui.protocol import BackendEvent, FrontendRequest
from treecode.ui.session_host import SessionHost, SessionHostConfig

log = logging.getLogger(__name__)

_PROTOCOL_PREFIX = "TCJSON:"


def _default_enable_shared_web() -> bool:
    return os.environ.get("TREECODE_DISABLE_SHARED_WEB", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def _maybe_open_web_console(ws_url: str) -> None:
    """If TREECODE_OPEN_WEB_CONSOLE is set, open browser to dev web UI with ?swarm_ws=."""
    raw = os.environ.get("TREECODE_OPEN_WEB_CONSOLE", "").strip().lower()
    if raw not in ("1", "true", "yes"):
        return
    base = (os.environ.get("TREECODE_WEB_CONSOLE_BASE") or "http://127.0.0.1:5173").rstrip("/")
    page = f"{base}/?swarm_ws={quote(ws_url, safe='')}"
    try:
        import webbrowser

        if not webbrowser.open(page):
            print(
                f"[treecode] Set up the web dev server (cd frontend/terminal && npm run dev:web), then open:\n  {page}",
                file=sys.stderr,
                flush=True,
            )
    except Exception as exc:
        log.warning("Could not open web console: %s", exc)
        print(f"[treecode] Open in browser:\n  {page}", file=sys.stderr, flush=True)


async def run_backend_host(
    *,
    model: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    cwd: str | None = None,
    api_client: SupportsStreamingMessages | None = None,
    stream_deltas: bool = False,
    debug_output: str | None = None,
    restore_messages: list[dict] | None = None,
    permission_mode: str | None = None,
    enable_shared_web: bool | None = None,
) -> int:
    """Run the structured React backend: SessionHost + optional shared WebSocket."""
    if cwd:
        os.chdir(cwd)

    if enable_shared_web is None:
        enable_shared_web = _default_enable_shared_web()

    config = SessionHostConfig(
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
        api_client=api_client,
        stream_deltas=stream_deltas,
        debug_output=debug_output,
        restore_messages=restore_messages,
        permission_mode=permission_mode,
        enable_shared_web=enable_shared_web,
    )
    host = SessionHost(config)

    # Register stdio before start() so ready/state_snapshot are not dropped (React TUI waits on TCJSON:ready).
    write_lock = asyncio.Lock()

    async def _stdio_emit(event: BackendEvent) -> None:
        async with write_lock:
            payload = _PROTOCOL_PREFIX + event.model_dump_json() + "\n"
            buffer = getattr(sys.stdout, "buffer", None)
            if buffer is not None:
                buffer.write(payload.encode("utf-8"))
                buffer.flush()
                return
            sys.stdout.write(payload)
            sys.stdout.flush()

    host.add_subscriber("stdio", _stdio_emit)

    await host.start()

    ws_server: Any | None = None
    if enable_shared_web:
        from treecode.swarm.console_ws import SwarmConsoleWsServer

        assert host.debugger is not None
        ws_server = SwarmConsoleWsServer(
            service=host.debugger,
            host="127.0.0.1",
            port=0,
            session_host=host,
        )
        await ws_server.start()
        host.set_ws_url(ws_server.ws_url)
        await host.emit(
            BackendEvent(type="shared_session_ready", ws_url=ws_server.ws_url)
        )
        print(
            f"[treecode] Swarm + session WebSocket (web console): {ws_server.ws_url}",
            file=sys.stderr,
            flush=True,
        )
        _maybe_open_web_console(ws_server.ws_url)

    reader = asyncio.create_task(_read_stdin_requests(host))
    try:
        code = await host.run_request_loop()
        return code
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader
        if ws_server is not None:
            await ws_server.stop()
        await host.close_debug_logger()


async def _read_stdin_requests(host: SessionHost) -> None:
    while True:
        raw = await asyncio.to_thread(sys.stdin.buffer.readline)
        if not raw:
            await host.enqueue_request(FrontendRequest(type="shutdown"))
            return
        payload = raw.decode("utf-8").strip()
        if not payload:
            continue
        try:
            request = FrontendRequest.model_validate_json(payload)
        except Exception as exc:  # pragma: no cover - defensive protocol handling
            await host.emit(
                BackendEvent(type="error", message=f"Invalid request: {exc}"),
                target_subscriber="stdio",
            )
            continue
        if request.type == "permission_response" and request.request_id:
            await host.handle_permission_response(request)
            continue
        if request.type == "question_response" and request.request_id:
            await host.handle_question_response(request)
            continue
        req = request.model_copy(
            update={"client_id": request.client_id or "stdio"}
        )
        await host.enqueue_request(req)


class ReactBackendHost(SessionHost):
    """Backward-compatible name for tests and docs (same as SessionHost)."""

    async def _read_requests(self) -> None:
        """Stdin reader used by unit tests (see ``tests/test_ui/test_react_backend.py``)."""
        await _read_stdin_requests(self)


class BackendHostConfig(SessionHostConfig):
    """Backward-compatible config name."""


__all__ = ["run_backend_host", "ReactBackendHost", "BackendHostConfig"]
