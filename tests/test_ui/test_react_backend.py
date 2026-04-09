"""Tests for the React backend host protocol."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.swarm.event_store import EventStore
from openharness.swarm.gather import GatherNodeResult, emit_gather_result
from openharness.ui.backend_host import BackendHostConfig, ReactBackendHost
from openharness.ui.protocol import BackendEvent
from openharness.ui.runtime import build_runtime, close_runtime, start_runtime


class StaticApiClient:
    """Fake streaming client for backend host tests."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def stream_message(self, request):
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text=self._text)]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


class SequenceApiClient:
    """Return a sequence of assistant-complete responses for successive turns."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def stream_message(self, request):
        del request
        text = self._responses.pop(0) if self._responses else ""
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text=text)]),
            usage=UsageSnapshot(input_tokens=2, output_tokens=3),
            stop_reason=None,
        )


class FakeBinaryStdout:
    """Capture protocol writes through a binary stdout buffer."""

    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_read_requests_resolves_permission_response_without_queueing(monkeypatch):
    host = ReactBackendHost(BackendHostConfig(api_client=StaticApiClient("unused")))
    fut = asyncio.get_running_loop().create_future()
    host._permission_requests["req-1"] = fut

    payload = b'{"type":"permission_response","request_id":"req-1","allowed":true}\n'

    class _FakeBuffer:
        def __init__(self):
            self._reads = 0

        def readline(self):
            self._reads += 1
            if self._reads == 1:
                return payload
            return b""

    class _FakeStdin:
        buffer = _FakeBuffer()

    monkeypatch.setattr("openharness.ui.backend_host.sys.stdin", _FakeStdin())

    await host._read_requests()

    assert fut.done()
    assert fut.result() is True
    queued = await host._request_queue.get()
    assert queued.type == "shutdown"
    assert host._request_queue.empty()


@pytest.mark.asyncio
async def test_backend_host_processes_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

    host = ReactBackendHost(BackendHostConfig(api_client=StaticApiClient("unused")))
    host._bundle = await build_runtime(api_client=StaticApiClient("unused"))
    events = []

    async def _emit(event):
        events.append(event)

    host.emit = _emit  # type: ignore[method-assign]
    await start_runtime(host._bundle)
    try:
        should_continue = await host._process_line("/version")
    finally:
        await close_runtime(host._bundle)

    assert should_continue is True
    assert any(
        event.type == "transcript_item"
        and event.item
        and event.item.role == "harness"
        and event.item.text == "/version"
        for event in events
    )
    assert any(
        event.type == "transcript_item"
        and event.item
        and event.item.role == "harness_result"
        and "OpenHarness" in event.item.text
        for event in events
    )
    assert any(event.type == "state_snapshot" for event in events)


@pytest.mark.asyncio
async def test_backend_host_processes_model_turn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

    host = ReactBackendHost(BackendHostConfig(api_client=StaticApiClient("hello from react backend")))
    host._bundle = await build_runtime(api_client=StaticApiClient("hello from react backend"))
    events = []

    async def _emit(event):
        events.append(event)

    host.emit = _emit  # type: ignore[method-assign]
    await start_runtime(host._bundle)
    try:
        should_continue = await host._process_line("hi")
    finally:
        await close_runtime(host._bundle)

    assert should_continue is True
    assert any(
        event.type == "assistant_complete" and event.message == "hello from react backend"
        for event in events
    )
    assert any(
        event.type == "assistant_complete"
        and event.item
        and event.item.role == "assistant"
        and "hello from react backend" in event.item.text
        for event in events
    )


@pytest.mark.asyncio
async def test_backend_host_execute_command_replays_slash_and_prompt_lines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    script = tmp_path / "setup.txt"
    script.write_text(
        "# bootstrap\n"
        "/version\n"
        "hello execute\n",
        encoding="utf-8",
    )

    host = ReactBackendHost(BackendHostConfig(api_client=StaticApiClient("hello from react backend")))
    host._bundle = await build_runtime(api_client=StaticApiClient("hello from react backend"))
    events = []

    async def _emit(event):
        events.append(event)

    host.emit = _emit  # type: ignore[method-assign]
    await start_runtime(host._bundle)
    try:
        should_continue = await host._process_line(f"/execute {script}")
    finally:
        await close_runtime(host._bundle)

    assert should_continue is True
    assert any(
        event.type == "transcript_item"
        and event.item
        and event.item.role == "harness_result"
        and "OpenHarness" in event.item.text
        for event in events
    )
    assert any(
        event.type == "assistant_complete"
        and event.item
        and event.item.role == "assistant"
        and "hello from react backend" in event.item.text
        for event in events
    )


@pytest.mark.asyncio
async def test_backend_host_execute_command_stops_on_unknown_slash_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    script = tmp_path / "bad-setup.txt"
    script.write_text(
        "/version\n"
        "/not-a-real-command\n"
        "hello execute\n",
        encoding="utf-8",
    )

    host = ReactBackendHost(BackendHostConfig(api_client=StaticApiClient("hello from react backend")))
    host._bundle = await build_runtime(api_client=StaticApiClient("hello from react backend"))
    events = []

    async def _emit(event):
        events.append(event)

    host.emit = _emit  # type: ignore[method-assign]
    await start_runtime(host._bundle)
    try:
        should_continue = await host._process_line(f"/execute {script}")
    finally:
        await close_runtime(host._bundle)

    assert should_continue is True
    assert any(
        event.type == "transcript_item"
        and event.item
        and event.item.role in ("system", "harness_result")
        and "line 2" in event.item.text
        and "/not-a-real-command" in event.item.text
        for event in events
    )
    assert not any(
        event.type == "assistant_complete"
        and event.item
        and event.item.role == "assistant"
        and "hello from react backend" in event.item.text
        for event in events
    )


@pytest.mark.asyncio
async def test_backend_host_gather_command_emits_visible_assistant_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "gather" / "gather_handshake.md"
    gather_dir = tmp_path / ".openharness" / "gather"
    gather_dir.mkdir(parents=True, exist_ok=True)
    (gather_dir / "gather_handshake.md").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    store = EventStore()

    async def fake_send_message(self, arguments, context):
        del self, context
        emit_gather_result(
            event_store=store,
            gather_id=arguments.message.split("--gather-id ", 1)[1].split(" ", 1)[0],
            agent_id=arguments.task_id,
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id=f"sess-{arguments.task_id}",
            result=GatherNodeResult(
                agent_id=arguments.task_id,
                status="ok",
                self_result={"agent_id": arguments.task_id, "role": "leaf", "ready": True},
                children=[],
                summary_text=f"{arguments.task_id} [leaf, ready]",
            ),
        )
        from openharness.tools.base import ToolResult

        return ToolResult(output=f"sent {arguments.task_id}")

    host = ReactBackendHost(
        BackendHostConfig(
            api_client=SequenceApiClient(
                [
                    "A summary\n```json\n"
                    '{"self_result":{"agent_id":"main@default","role":"branch","ready":true},'
                    '"summary_text":"main@default [branch, ready]\\n- child-a@default [leaf, ready]"}\n'
                    "```"
                ]
            )
        )
    )
    host._bundle = await build_runtime(
        api_client=SequenceApiClient(
            [
                "A summary\n```json\n"
                '{"self_result":{"agent_id":"main@default","role":"branch","ready":true},'
                '"summary_text":"main@default [branch, ready]\\n- child-a@default [leaf, ready]"}\n'
                "```"
            ]
        ),
        swarm_tool_metadata={
            "swarm_agent_id": "main@default",
            "swarm_root_agent_id": "main@default",
            "swarm_lineage_path": ("main@default",),
        },
    )
    events = []

    async def _emit(event):
        events.append(event)

    monkeypatch.setattr("openharness.tools.swarm_gather_tool.get_event_store", lambda: store)
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.resolve_live_child_agent_ids",
        lambda context, current_agent_id: ["child-a@default"],
    )
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.SendMessageTool.execute",
        fake_send_message,
    )
    host.emit = _emit  # type: ignore[method-assign]
    await start_runtime(host._bundle)
    try:
        should_continue = await host._process_line('/gather --spec gather_handshake "collect handshake"')
    finally:
        await close_runtime(host._bundle)

    assert should_continue is True
    assert any(
        event.type == "assistant_complete"
        and event.item
        and event.item.role == "assistant"
        and "main@default [branch, ready]" in event.item.text
        for event in events
    )


@pytest.mark.asyncio
async def test_backend_host_command_does_not_reset_cli_overrides(tmp_path, monkeypatch):
    """Regression: slash commands should not snap model/provider back to persisted defaults.

    When the session is launched with CLI overrides (e.g. ``-m 5.4 --api-format openai``),
    issuing a command like /fast triggers a UI state refresh. That refresh must
    preserve the effective session settings, not reload ~/.openharness/settings.json
    verbatim.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

    host = ReactBackendHost(BackendHostConfig(api_client=StaticApiClient("unused")))
    host._bundle = await build_runtime(
        api_client=StaticApiClient("unused"),
        model="5.4",
        api_format="openai",
    )
    events = []

    async def _emit(event):
        events.append(event)

    host.emit = _emit  # type: ignore[method-assign]
    await start_runtime(host._bundle)
    try:
        # Sanity: the initial session state reflects CLI overrides.
        assert host._bundle.app_state.get().model == "5.4"
        # detect_provider() uses base_url/model heuristics; empty base_url → "anthropic"
        assert host._bundle.app_state.get().provider == "anthropic"

        # Run a command that triggers sync_app_state.
        await host._process_line("/fast show")

        # CLI overrides should remain in effect.
        assert host._bundle.app_state.get().model == "5.4"
        assert host._bundle.app_state.get().provider == "anthropic"
    finally:
        await close_runtime(host._bundle)


@pytest.mark.asyncio
async def test_backend_host_emits_utf8_protocol_bytes(monkeypatch):
    host = ReactBackendHost(BackendHostConfig())
    fake_stdout = FakeBinaryStdout()
    monkeypatch.setattr("openharness.ui.backend_host.sys.stdout", fake_stdout)

    async def _stdio_emit(event: BackendEvent) -> None:
        payload = "OHJSON:" + event.model_dump_json() + "\n"
        fake_stdout.buffer.write(payload.encode("utf-8"))

    host.add_subscriber("test_stdio", _stdio_emit)
    await host.emit(BackendEvent(type="assistant_delta", message="你好😊"))

    raw = fake_stdout.buffer.getvalue()
    assert raw.startswith(b"OHJSON:")
    decoded = raw.decode("utf-8").strip()
    payload = json.loads(decoded.removeprefix("OHJSON:"))
    assert payload["type"] == "assistant_delta"
    assert payload["message"] == "你好😊"
