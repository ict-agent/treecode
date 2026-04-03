"""Interactive session entry points."""

from __future__ import annotations

import json
import sys
from typing import Any

from openharness.api.client import SupportsStreamingMessages
from openharness.engine.stream_events import StreamEvent
from openharness.ui.backend_host import run_backend_host
from openharness.ui.react_launcher import launch_react_tui
from openharness.ui.runtime import build_runtime, close_runtime, handle_line, start_runtime

# Debug logger (lazy import to avoid circular deps)
_debug_logger_instance: Any = None


async def run_repl(
    *,
    prompt: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_client: SupportsStreamingMessages | None = None,
    backend_only: bool = False,
    stream_deltas: bool = False,
    debug_output: str | None = None,
) -> None:
    """Run the default OpenHarness interactive application (React TUI)."""
    if backend_only:
        await run_backend_host(
            cwd=cwd,
            model=model,
            base_url=base_url,
            system_prompt=system_prompt,
            api_key=api_key,
            api_client=api_client,
            stream_deltas=stream_deltas,
            debug_output=debug_output,
        )
        return

    exit_code = await launch_react_tui(
        prompt=prompt,
        cwd=cwd,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        debug_output=debug_output,
    )
    if exit_code != 0:
        raise SystemExit(exit_code)


async def run_print_mode(
    *,
    prompt: str,
    output_format: str = "text",
    cwd: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    api_key: str | None = None,
    api_client: SupportsStreamingMessages | None = None,
    permission_mode: str | None = None,
    max_turns: int | None = None,
    debug_output: str | None = None,
) -> None:
    """Non-interactive mode: submit prompt, stream output, exit."""
    from openharness.engine.stream_events import (
        AssistantTextDelta,
        AssistantTurnComplete,
        MaxTurnsReached,
        ToolExecutionCompleted,
        ToolExecutionStarted,
        UserMessage,
    )

    # Initialize debug logger if requested
    debug_logger = None
    if debug_output:
        from openharness.debug.logger import DebugLogger
        debug_logger = DebugLogger(debug_output)

    async def _noop_permission(tool_name: str, reason: str) -> bool:
        return True

    async def _noop_ask(question: str) -> str:
        return ""

    bundle = await build_runtime(
        prompt=prompt,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_client=api_client,
        permission_prompt=_noop_permission,
        ask_user_prompt=_noop_ask,
    )
    await start_runtime(bundle)

    collected_text = ""
    events_list: list[dict] = []

    # Log initial user input
    if debug_logger is not None:
        await debug_logger(UserMessage(text=prompt))

    try:
        async def _print_system(message: str) -> None:
            nonlocal collected_text
            if output_format == "text":
                print(message, file=sys.stderr)
            elif output_format == "stream-json":
                obj = {"type": "system", "message": message}
                print(json.dumps(obj), flush=True)
                events_list.append(obj)

        async def _render_event(event: StreamEvent) -> None:
            nonlocal collected_text
            if isinstance(event, AssistantTextDelta):
                collected_text += event.text
                if output_format == "text":
                    sys.stdout.write(event.text)
                    sys.stdout.flush()
                elif output_format == "stream-json":
                    obj = {"type": "assistant_delta", "text": event.text}
                    print(json.dumps(obj), flush=True)
                    events_list.append(obj)
            elif isinstance(event, AssistantTurnComplete):
                if output_format == "text":
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                elif output_format == "stream-json":
                    obj = {"type": "assistant_complete", "text": event.message.text.strip()}
                    print(json.dumps(obj), flush=True)
                    events_list.append(obj)
            elif isinstance(event, ToolExecutionStarted):
                if output_format == "stream-json":
                    obj = {"type": "tool_started", "tool_name": event.tool_name, "tool_input": event.tool_input}
                    print(json.dumps(obj), flush=True)
                    events_list.append(obj)
            elif isinstance(event, ToolExecutionCompleted):
                if output_format == "stream-json":
                    obj = {"type": "tool_completed", "tool_name": event.tool_name, "output": event.output, "is_error": event.is_error}
                    print(json.dumps(obj), flush=True)
                    events_list.append(obj)
            elif isinstance(event, MaxTurnsReached):
                if output_format == "text":
                    print(f"\n[Max turns reached ({event.max_turns})]", file=sys.stderr)
                elif output_format == "stream-json":
                    obj = {"type": "max_turns_reached", "max_turns": event.max_turns}
                    print(json.dumps(obj), flush=True)
                    events_list.append(obj)

            # Debug logging (runs after normal rendering)
            if debug_logger is not None:
                await debug_logger(event)

        async def _clear_output() -> None:
            pass

        await handle_line(
            bundle,
            prompt,
            print_system=_print_system,
            render_event=_render_event,
            clear_output=_clear_output,
        )

        if output_format == "json":
            result = {"type": "result", "text": collected_text.strip()}
            print(json.dumps(result))
    finally:
        if debug_logger is not None:
            await debug_logger.close()
        await close_runtime(bundle)
