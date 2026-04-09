"""Tests for optional `` !!`` suffix on slash commands (record in LLM context)."""

from __future__ import annotations

import pytest

from openharness.commands import create_default_command_registry
from openharness.ui.runtime import strip_slash_remember_suffix


def test_strip_remember_suffix_registered_command() -> None:
    reg = create_default_command_registry()
    line, remember = strip_slash_remember_suffix("/version !!", reg)
    assert remember is True
    assert line == "/version"


def test_strip_remember_no_space_before_bang_not_stripped() -> None:
    reg = create_default_command_registry()
    line, remember = strip_slash_remember_suffix("/version!!", reg)
    assert remember is False
    assert line == "/version!!"


def test_strip_remember_unknown_slash_unchanged() -> None:
    reg = create_default_command_registry()
    line, remember = strip_slash_remember_suffix("/not-a-real-command !!", reg)
    assert remember is False
    assert line == "/not-a-real-command !!"


def test_gather_delegated_command_appends_remember_marker() -> None:
    from openharness.tools.swarm_gather_tool import _build_delegated_gather_command

    plain = _build_delegated_gather_command(
        request="hi",
        spec_name="gather_num",
        gather_id="g1",
        origin_agent_id="main@default",
        remember_for_model=False,
    )
    assert not plain.endswith(" !!")

    marked = _build_delegated_gather_command(
        request="hi",
        spec_name="gather_num",
        gather_id="g1",
        origin_agent_id="main@default",
        remember_for_model=True,
    )
    assert marked.endswith(" !!")


def test_recursive_gather_command_appends_remember_marker() -> None:
    from openharness.swarm.gather import _build_recursive_gather_command

    base = _build_recursive_gather_command(
        gather_id="g1",
        spec_name="s",
        request="r",
        origin_agent_id="A@default",
        remember_for_model=False,
    )
    assert not base.endswith(" !!")

    m = _build_recursive_gather_command(
        gather_id="g1",
        spec_name="s",
        request="r",
        origin_agent_id="A@default",
        remember_for_model=True,
    )
    assert m.endswith(" !!")


@pytest.mark.asyncio
async def test_slash_remember_appends_user_note(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

    from openharness.api.client import ApiMessageCompleteEvent
    from openharness.api.usage import UsageSnapshot
    from openharness.engine.messages import ConversationMessage, TextBlock
    from openharness.ui.runtime import build_runtime, close_runtime, start_runtime, _execute_input_line
    from openharness.engine.stream_events import StreamEvent

    class _Static:
        async def stream_message(self, request):
            del request
            yield ApiMessageCompleteEvent(
                message=ConversationMessage(role="assistant", content=[TextBlock(text="x")]),
                usage=UsageSnapshot(input_tokens=1, output_tokens=1),
                stop_reason=None,
            )

    async def _print_system(message: str, *, harness_output: bool = False) -> None:
        del message, harness_output

    async def _render_event(_event: StreamEvent) -> None:
        return None

    async def _clear() -> None:
        return None

    bundle = await build_runtime(api_client=_Static())
    await start_runtime(bundle)
    try:
        await _execute_input_line(
            bundle,
            "/version !!",
            print_system=_print_system,
            render_event=_render_event,
            clear_output=_clear,
        )
    finally:
        await close_runtime(bundle)

    msgs = bundle.engine.messages
    assert len(msgs) >= 1
    last = msgs[-1]
    assert last.role == "user"
    assert "Slash command recorded for model context" in last.text
    assert "/version" in last.text
