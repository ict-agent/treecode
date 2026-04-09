"""Shared runtime assembly for headless and Textual UIs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from openharness.api.client import AnthropicApiClient, SupportsStreamingMessages
from openharness.api.openai_client import OpenAICompatibleClient
from openharness.api.provider import auth_status, detect_provider
from openharness.bridge import get_bridge_manager
from openharness.commands import CommandContext, CommandResult, create_default_command_registry
from openharness.config import get_config_file_path, load_settings
from openharness.engine import QueryEngine
from openharness.engine.messages import ConversationMessage
from openharness.engine.stream_events import StreamEvent
from openharness.hooks import HookEvent, HookExecutionContext, HookExecutor, load_hook_registry
from openharness.hooks.hot_reload import HookReloader
from openharness.mcp.client import McpClientManager
from openharness.mcp.config import load_mcp_server_configs
from openharness.permissions import PermissionChecker
from openharness.plugins import load_plugins
from openharness.prompts import build_runtime_system_prompt
from openharness.state import AppState, AppStateStore
from openharness.services.session_storage import save_session_snapshot
from openharness.tools import ToolRegistry, create_default_tool_registry
from openharness.tools.swarm_gather_tool import build_engine_gather_local_runner
from openharness.keybindings import load_keybindings

PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]
SystemPrinter = Callable[[str], Awaitable[None]]
StreamRenderer = Callable[[StreamEvent], Awaitable[None]]
ClearHandler = Callable[[], Awaitable[None]]


@dataclass
class RuntimeBundle:
    """Shared runtime objects for one interactive session."""

    api_client: SupportsStreamingMessages
    cwd: str
    mcp_manager: McpClientManager
    tool_registry: ToolRegistry
    app_state: AppStateStore
    hook_executor: HookExecutor
    engine: QueryEngine
    commands: object
    external_api_client: bool
    session_id: str = ""
    settings_overrides: dict[str, Any] = field(default_factory=dict)

    def current_settings(self):
        """Return the effective settings for this session.

        We persist most settings to disk (``~/.openharness/settings.json``), but
        CLI options like ``--model``/``--api-format`` should remain in effect for
        the lifetime of the running process. Without this overlay, issuing any
        slash command (e.g. ``/fast``) would refresh UI state from disk and
        "snap back" the model/provider to whatever is stored in the config file.
        """
        return load_settings().merge_cli_overrides(**self.settings_overrides)

    def current_plugins(self):
        """Return currently visible plugins for the working tree."""
        return load_plugins(self.current_settings(), self.cwd)

    def hook_summary(self) -> str:
        """Return the current hook summary."""
        return load_hook_registry(self.current_settings(), self.current_plugins()).summary()

    def plugin_summary(self) -> str:
        """Return the current plugin summary."""
        plugins = self.current_plugins()
        if not plugins:
            return "No plugins discovered."
        lines = ["Plugins:"]
        for plugin in plugins:
            state = "enabled" if plugin.enabled else "disabled"
            lines.append(f"- {plugin.manifest.name} [{state}] {plugin.manifest.description}")
        return "\n".join(lines)

    def mcp_summary(self) -> str:
        """Return the current MCP summary."""
        statuses = self.mcp_manager.list_statuses()
        if not statuses:
            return "No MCP servers configured."
        lines = ["MCP servers:"]
        for status in statuses:
            suffix = f" - {status.detail}" if status.detail else ""
            lines.append(f"- {status.name}: {status.state}{suffix}")
            if status.tools:
                lines.append(f"  tools: {', '.join(tool.name for tool in status.tools)}")
            if status.resources:
                lines.append(f"  resources: {', '.join(resource.uri for resource in status.resources)}")
        return "\n".join(lines)


async def build_runtime(
    *,
    prompt: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    api_client: SupportsStreamingMessages | None = None,
    permission_prompt: PermissionPrompt | None = None,
    ask_user_prompt: AskUserPrompt | None = None,
    restore_messages: list[dict] | None = None,
    cwd: str | Path | None = None,
    extra_system_prompt_suffix: str | None = None,
    swarm_tool_metadata: dict[str, object] | None = None,
    permission_mode: str | None = None,
) -> RuntimeBundle:
    """Build the shared runtime for an OpenHarness session."""
    settings_overrides: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "system_prompt": system_prompt,
        "api_key": api_key,
        "api_format": api_format,
        "permission_mode": permission_mode,
    }
    settings = load_settings().merge_cli_overrides(**settings_overrides)
    cwd = str(Path(cwd).resolve()) if cwd is not None else str(Path.cwd().resolve())
    plugins = load_plugins(settings, cwd)
    if api_client:
        resolved_api_client = api_client
    elif settings.api_format == "openai":
        resolved_api_client = OpenAICompatibleClient(
            api_key=settings.resolve_api_key(),
            base_url=settings.base_url,
        )
    else:
        resolved_api_client = AnthropicApiClient(
            api_key=settings.resolve_api_key(),
            base_url=settings.base_url,
        )
    mcp_manager = McpClientManager(load_mcp_server_configs(settings, plugins))
    await mcp_manager.connect_all()
    tool_registry = create_default_tool_registry(mcp_manager)
    provider = detect_provider(settings)
    bridge_manager = get_bridge_manager()
    app_state = AppStateStore(
        AppState(
            model=settings.model,
            permission_mode=settings.permission.mode.value,
            theme=settings.theme,
            cwd=cwd,
            provider=provider.name,
            auth_status=auth_status(settings),
            base_url=settings.base_url or "",
            vim_enabled=settings.vim_mode,
            voice_enabled=settings.voice_mode,
            voice_available=provider.voice_supported,
            voice_reason=provider.voice_reason,
            fast_mode=settings.fast_mode,
            effort=settings.effort,
            passes=settings.passes,
            mcp_connected=sum(1 for status in mcp_manager.list_statuses() if status.state == "connected"),
            mcp_failed=sum(1 for status in mcp_manager.list_statuses() if status.state == "failed"),
            bridge_sessions=len(bridge_manager.list_sessions()),
            output_style=settings.output_style,
            keybindings=load_keybindings(),
        )
    )
    hook_reloader = HookReloader(get_config_file_path())
    hook_executor = HookExecutor(
        hook_reloader.current_registry() if api_client is None else load_hook_registry(settings, plugins),
        HookExecutionContext(
            cwd=Path(cwd).resolve(),
            api_client=resolved_api_client,
            default_model=settings.model,
        ),
    )
    from uuid import uuid4

    session_id = os.environ.get("OPENHARNESS_SWARM_SESSION_ID") or uuid4().hex[:12]
    swarm_lineage_path = os.environ.get("OPENHARNESS_SWARM_LINEAGE_PATH", "")
    base_runtime_prompt = build_runtime_system_prompt(settings, cwd=cwd, latest_user_prompt=prompt)
    engine_system_prompt = (
        f"{base_runtime_prompt}\n\n{extra_system_prompt_suffix}"
        if extra_system_prompt_suffix
        else base_runtime_prompt
    )
    tool_meta: dict[str, object] = {
        "mcp_manager": mcp_manager,
        "bridge_manager": bridge_manager,
        "session_id": session_id,
        **(
            {"swarm_agent_id": os.environ["OPENHARNESS_SWARM_AGENT_ID"]}
            if os.environ.get("OPENHARNESS_SWARM_AGENT_ID")
            else {}
        ),
        **(
            {"swarm_parent_agent_id": os.environ["OPENHARNESS_SWARM_PARENT_AGENT_ID"]}
            if os.environ.get("OPENHARNESS_SWARM_PARENT_AGENT_ID")
            else {}
        ),
        **(
            {"swarm_root_agent_id": os.environ["OPENHARNESS_SWARM_ROOT_AGENT_ID"]}
            if os.environ.get("OPENHARNESS_SWARM_ROOT_AGENT_ID")
            else {}
        ),
        **(
            {"swarm_lineage_path": tuple(filter(None, swarm_lineage_path.split("::")))}
            if swarm_lineage_path
            else {}
        ),
    }
    if swarm_tool_metadata:
        tool_meta.update(swarm_tool_metadata)
    if "swarm_leader_session_id" not in tool_meta:
        env_leader = os.environ.get("OPENHARNESS_SWARM_LEADER_SESSION_ID")
        if env_leader:
            tool_meta["swarm_leader_session_id"] = env_leader
        elif not os.environ.get("OPENHARNESS_SWARM_AGENT_ID"):
            # Leader process (shared TUI / main): own the session id namespace for swarm agents.
            tool_meta["swarm_leader_session_id"] = session_id
    engine = QueryEngine(
        api_client=resolved_api_client,
        tool_registry=tool_registry,
        permission_checker=PermissionChecker(settings.permission),
        cwd=cwd,
        model=settings.model,
        system_prompt=engine_system_prompt,
        max_tokens=settings.max_tokens,
        max_turns=settings.max_turns,
        permission_prompt=permission_prompt,
        ask_user_prompt=ask_user_prompt,
        hook_executor=hook_executor,
        tool_metadata=tool_meta,
    )
    tool_meta["run_gather_local"] = build_engine_gather_local_runner(engine)
    # Restore messages from a saved session if provided
    if restore_messages:
        restored = [
            ConversationMessage.model_validate(m) for m in restore_messages
        ]
        engine.load_messages(restored)

    return RuntimeBundle(
        api_client=resolved_api_client,
        cwd=cwd,
        mcp_manager=mcp_manager,
        tool_registry=tool_registry,
        app_state=app_state,
        hook_executor=hook_executor,
        engine=engine,
        commands=create_default_command_registry(),
        external_api_client=api_client is not None,
        session_id=session_id,
        settings_overrides=settings_overrides,
    )


async def start_runtime(bundle: RuntimeBundle) -> None:
    """Run session start hooks."""
    await bundle.hook_executor.execute(
        HookEvent.SESSION_START,
        {"cwd": bundle.cwd, "event": HookEvent.SESSION_START.value},
    )


async def close_runtime(bundle: RuntimeBundle) -> None:
    """Close runtime-owned resources."""
    await bundle.mcp_manager.close()
    await bundle.hook_executor.execute(
        HookEvent.SESSION_END,
        {"cwd": bundle.cwd, "event": HookEvent.SESSION_END.value},
    )


def sync_app_state(bundle: RuntimeBundle) -> None:
    """Refresh UI state from current settings and dynamic keybindings."""
    settings = bundle.current_settings()
    provider = detect_provider(settings)
    bundle.app_state.set(
        model=settings.model,
        permission_mode=settings.permission.mode.value,
        theme=settings.theme,
        cwd=bundle.cwd,
        provider=provider.name,
        auth_status=auth_status(settings),
        base_url=settings.base_url or "",
        vim_enabled=settings.vim_mode,
        voice_enabled=settings.voice_mode,
        voice_available=provider.voice_supported,
        voice_reason=provider.voice_reason,
        fast_mode=settings.fast_mode,
        effort=settings.effort,
        passes=settings.passes,
        mcp_connected=sum(1 for status in bundle.mcp_manager.list_statuses() if status.state == "connected"),
        mcp_failed=sum(1 for status in bundle.mcp_manager.list_statuses() if status.state == "failed"),
        bridge_sessions=len(get_bridge_manager().list_sessions()),
        output_style=settings.output_style,
        keybindings=load_keybindings(),
    )


async def _drain_leader_mailbox() -> list[str]:
    """Drain unread idle_notifications from the leader mailbox.

    Returns a list of human-readable notification strings to be shown as
    system messages before the next LLM turn.  Only reads idle_notification
    messages and marks them as read.
    """
    try:
        from openharness.swarm.mailbox import TeammateMailbox
        mailbox = TeammateMailbox(team_name="default", agent_id="leader")
        messages = await mailbox.read_all(unread_only=True)
        notifications: list[str] = []
        for msg in messages:
            if msg.type == "idle_notification":
                summary = msg.payload.get("summary", f"Agent {msg.sender} finished")
                notifications.append(
                    f"[Sub-agent notification] {summary}"
                )
                await mailbox.mark_read(msg.id)
        return notifications
    except Exception:
        return []


async def handle_line(
    bundle: RuntimeBundle,
    line: str,
    *,
    print_system: SystemPrinter,
    render_event: StreamRenderer,
    clear_output: ClearHandler,
) -> bool:
    """Handle one submitted line for either headless or TUI rendering."""
    result = await _execute_input_line(
        bundle,
        line,
        print_system=print_system,
        render_event=render_event,
        clear_output=clear_output,
    )
    return bool(result.get("should_continue", True))


async def _execute_input_line(
    bundle: RuntimeBundle,
    line: str,
    *,
    print_system: SystemPrinter,
    render_event: StreamRenderer,
    clear_output: ClearHandler,
) -> dict[str, object]:
    """Execute one input line and return structured status for reuse by `/execute`."""

    if not bundle.external_api_client:
        bundle.hook_executor.update_registry(
            load_hook_registry(bundle.current_settings(), bundle.current_plugins())
        )

    async def _replay_input_line(inner_line: str) -> dict[str, object]:
        if inner_line.strip().startswith("/") and bundle.commands.lookup(inner_line) is None:
            return {
                "ok": False,
                "should_continue": True,
                "error": f"Unknown slash command: {inner_line.strip()}",
            }
        return await _execute_input_line(
            bundle,
            inner_line,
            print_system=print_system,
            render_event=render_event,
            clear_output=clear_output,
        )

    async def _run_model_turn(prompt: str) -> str:
        settings = bundle.current_settings()
        bundle.engine.set_system_prompt(
            build_runtime_system_prompt(settings, cwd=bundle.cwd, latest_user_prompt=prompt)
        )
        final_text = ""
        async for event in bundle.engine.submit_message(prompt):
            await render_event(event)
            from openharness.engine.stream_events import AssistantTurnComplete

            if isinstance(event, AssistantTurnComplete):
                final_text = event.message.text.strip()
        save_session_snapshot(
            cwd=bundle.cwd,
            model=settings.model,
            system_prompt=build_runtime_system_prompt(settings, cwd=bundle.cwd, latest_user_prompt=prompt),
            messages=bundle.engine.messages,
            usage=bundle.engine.total_usage,
            session_id=bundle.session_id,
        )
        sync_app_state(bundle)
        return final_text

    parsed = bundle.commands.lookup(line)
    if parsed is not None:
        command, args = parsed
        result = await command.handler(
            args,
            CommandContext(
                engine=bundle.engine,
                hooks_summary=bundle.hook_summary(),
                mcp_summary=bundle.mcp_summary(),
                plugin_summary=bundle.plugin_summary(),
                cwd=bundle.cwd,
                tool_registry=bundle.tool_registry,
                app_state=bundle.app_state,
                replay_input_line=_replay_input_line,
                run_model_turn=_run_model_turn,
            ),
        )
        await _render_command_result(result, print_system, clear_output, render_event)
        sync_app_state(bundle)
        return {
            "ok": not _command_result_indicates_error(result),
            "should_continue": not result.should_exit,
            "error": result.message if _command_result_indicates_error(result) else None,
        }

    # Drain leader mailbox: inject any pending idle_notifications from sub-agents
    # as system messages so the LLM sees them on this turn.
    pending = await _drain_leader_mailbox()
    for notification in pending:
        await print_system(notification)

    settings = bundle.current_settings()
    bundle.engine.set_system_prompt(
        build_runtime_system_prompt(settings, cwd=bundle.cwd, latest_user_prompt=line)
    )
    async for event in bundle.engine.submit_message(line):
        await render_event(event)
    save_session_snapshot(
        cwd=bundle.cwd,
        model=settings.model,
        system_prompt=build_runtime_system_prompt(settings, cwd=bundle.cwd, latest_user_prompt=line),
        messages=bundle.engine.messages,
        usage=bundle.engine.total_usage,
        session_id=bundle.session_id,
    )
    sync_app_state(bundle)
    return {"ok": True, "should_continue": True, "error": None}


def _command_result_indicates_error(result: CommandResult) -> bool:
    """Best-effort detection for slash-command failure messages used by `/execute`."""

    message = (result.message or "").strip()
    return bool(
        message.startswith("Usage:")
        or message.startswith("Unknown ")
        or message.startswith("Error:")
        or message.startswith("`/")
    )


async def _render_command_result(
    result: CommandResult,
    print_system: SystemPrinter,
    clear_output: ClearHandler,
    render_event: StreamRenderer | None = None,
) -> None:
    if result.clear_screen:
        await clear_output()
    if result.replay_messages and render_event is not None:
        # Replay restored conversation messages as transcript events
        from openharness.engine.stream_events import AssistantTextDelta, AssistantTurnComplete
        from openharness.api.usage import UsageSnapshot

        await clear_output()
        await print_system("Session restored:")
        for msg in result.replay_messages:
            if msg.role == "user":
                await print_system(f"> {msg.text}")
            elif msg.role == "assistant" and msg.text.strip():
                await render_event(AssistantTextDelta(text=msg.text))
                await render_event(AssistantTurnComplete(message=msg, usage=UsageSnapshot()))
    if result.message and not result.replay_messages:
        await print_system(result.message)
