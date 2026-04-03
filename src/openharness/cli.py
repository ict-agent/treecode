"""CLI entry point using typer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="openharness",
    help=(
        "Oh my Harness! An AI-powered coding assistant.\n\n"
        "Starts an interactive session by default, use -p/--print for non-interactive output."
    ),
    add_completion=False,
    rich_markup_mode="rich",
    invoke_without_command=True,
)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

mcp_app = typer.Typer(name="mcp", help="Manage MCP servers")
plugin_app = typer.Typer(name="plugin", help="Manage plugins")
auth_app = typer.Typer(name="auth", help="Manage authentication")
agent_debug_app = typer.Typer(name="agent-debug", help="External agent E2E debugging utilities")

app.add_typer(mcp_app)
app.add_typer(plugin_app)
app.add_typer(auth_app)
app.add_typer(agent_debug_app)


# ---- mcp subcommands ----

@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers."""
    from openharness.config import load_settings
    from openharness.mcp.config import load_mcp_server_configs
    from openharness.plugins import load_plugins

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    configs = load_mcp_server_configs(settings, plugins)
    if not configs:
        print("No MCP servers configured.")
        return
    for name, cfg in configs.items():
        transport = cfg.get("transport", cfg.get("command", "unknown"))
        print(f"  {name}: {transport}")


@mcp_app.command("add")
def mcp_add(
    name: str = typer.Argument(..., help="Server name"),
    config_json: str = typer.Argument(..., help="Server config as JSON string"),
) -> None:
    """Add an MCP server configuration."""
    from openharness.config import load_settings, save_settings

    settings = load_settings()
    try:
        cfg = json.loads(config_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    if not isinstance(settings.mcp_servers, dict):
        settings.mcp_servers = {}
    settings.mcp_servers[name] = cfg
    save_settings(settings)
    print(f"Added MCP server: {name}")


@mcp_app.command("remove")
def mcp_remove(
    name: str = typer.Argument(..., help="Server name to remove"),
) -> None:
    """Remove an MCP server configuration."""
    from openharness.config import load_settings, save_settings

    settings = load_settings()
    if not isinstance(settings.mcp_servers, dict) or name not in settings.mcp_servers:
        print(f"MCP server not found: {name}", file=sys.stderr)
        raise typer.Exit(1)
    del settings.mcp_servers[name]
    save_settings(settings)
    print(f"Removed MCP server: {name}")


# ---- plugin subcommands ----

@plugin_app.command("list")
def plugin_list() -> None:
    """List installed plugins."""
    from openharness.config import load_settings
    from openharness.plugins import load_plugins

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    if not plugins:
        print("No plugins installed.")
        return
    for plugin in plugins:
        status = "enabled" if plugin.enabled else "disabled"
        print(f"  {plugin.name} [{status}] - {plugin.description or ''}")


@plugin_app.command("install")
def plugin_install(
    source: str = typer.Argument(..., help="Plugin source (path or URL)"),
) -> None:
    """Install a plugin from a source path."""
    from openharness.plugins.installer import install_plugin_from_path

    result = install_plugin_from_path(source)
    print(f"Installed plugin: {result}")


@plugin_app.command("uninstall")
def plugin_uninstall(
    name: str = typer.Argument(..., help="Plugin name to uninstall"),
) -> None:
    """Uninstall a plugin."""
    from openharness.plugins.installer import uninstall_plugin

    uninstall_plugin(name)
    print(f"Uninstalled plugin: {name}")


# ---- auth subcommands ----

@auth_app.command("status")
def auth_status_cmd() -> None:
    """Show authentication status."""
    from openharness.api.provider import auth_status, detect_provider
    from openharness.config import load_settings

    settings = load_settings()
    provider = detect_provider(settings)
    status = auth_status(settings)
    print(f"Provider: {provider}")
    print(f"Status:   {status}")


@auth_app.command("login")
def auth_login(
    api_key: str | None = typer.Option(None, "--api-key", "-k", help="API key"),
) -> None:
    """Configure authentication."""
    from openharness.config import load_settings, save_settings

    if not api_key:
        api_key = typer.prompt("Enter your API key", hide_input=True)
    settings = load_settings()
    settings.api_key = api_key
    save_settings(settings)
    print("API key saved.")


@auth_app.command("logout")
def auth_logout() -> None:
    """Remove stored authentication."""
    from openharness.config import load_settings, save_settings

    settings = load_settings()
    settings.api_key = None
    save_settings(settings)
    print("Authentication cleared.")


# ---- agent-debug subcommands ----

@agent_debug_app.command("start")
def debug_start(
    session_id: str = typer.Argument(..., help="Unique identifier for the test session"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Extract raw LLM prompt payloads into pretty_output_verbose.txt"),
) -> None:
    """Start an OpenHarness backend daemon in the background for agent debugging."""
    from openharness.agent_debug import start_debug_session
    start_debug_session(session_id, verbose=verbose)


@agent_debug_app.command("send")
def debug_send(
    session_id: str = typer.Argument(..., help="The active session identifier"),
    message: str = typer.Argument(..., help="Prompt text or raw raw JSON string"),
) -> None:
    """Submit a query to an active background session and synchronously wait for JSON completion."""
    from openharness.agent_debug import send_debug_message
    send_debug_message(session_id, message)


@agent_debug_app.command("stop")
def debug_stop(
    session_id: str = typer.Argument(..., help="Identifier of the session to terminate"),
) -> None:
    """Silently murder the background debugging process and clean context."""
    from openharness.agent_debug import stop_debug_session
    stop_debug_session(session_id)


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    # --- Session ---
    continue_session: bool = typer.Option(
        False,
        "--continue",
        "-c",
        help="Continue the most recent conversation in the current directory",
        rich_help_panel="Session",
    ),
    resume: str | None = typer.Option(
        None,
        "--resume",
        "-r",
        help="Resume a conversation by session ID, or open picker",
        rich_help_panel="Session",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Set a display name for this session",
        rich_help_panel="Session",
    ),
    # --- Model & Effort ---
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model alias (e.g. 'sonnet', 'opus') or full model ID",
        rich_help_panel="Model & Effort",
    ),
    effort: str | None = typer.Option(
        None,
        "--effort",
        help="Effort level for the session (low, medium, high, max)",
        rich_help_panel="Model & Effort",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Override verbose mode setting from config",
        rich_help_panel="Model & Effort",
    ),
    max_turns: int | None = typer.Option(
        None,
        "--max-turns",
        help="Maximum number of agentic turns (useful with --print)",
        rich_help_panel="Model & Effort",
    ),
    # --- Debug ---
    debug_output: str | None = typer.Option(
        None,
        "--debug-output",
        help="Write debug log to a custom file path",
        rich_help_panel="Debug",
    ),
    debug_flag: bool = typer.Option(
        False,
        "--debug-log",
        "-D",
        help="Enable debug logging to debug.log (or use --debug-output for custom path)",
        rich_help_panel="Debug",
    ),
    # --- Output ---
    print_mode: str | None = typer.Option(
        None,
        "--print",
        "-p",
        help="Print response and exit. Pass your prompt as the value: -p 'your prompt'",
        rich_help_panel="Output",
    ),
    output_format: str | None = typer.Option(
        None,
        "--output-format",
        help="Output format with --print: text (default), json, or stream-json",
        rich_help_panel="Output",
    ),
    # --- Permissions ---
    permission_mode: str | None = typer.Option(
        None,
        "--permission-mode",
        help="Permission mode: default, plan, or full_auto",
        rich_help_panel="Permissions",
    ),
    dangerously_skip_permissions: bool = typer.Option(
        False,
        "--dangerously-skip-permissions",
        help="Bypass all permission checks (only for sandboxed environments)",
        rich_help_panel="Permissions",
    ),
    allowed_tools: Optional[list[str]] = typer.Option(
        None,
        "--allowed-tools",
        help="Comma or space-separated list of tool names to allow",
        rich_help_panel="Permissions",
    ),
    disallowed_tools: Optional[list[str]] = typer.Option(
        None,
        "--disallowed-tools",
        help="Comma or space-separated list of tool names to deny",
        rich_help_panel="Permissions",
    ),
    # --- System & Context ---
    system_prompt: str | None = typer.Option(
        None,
        "--system-prompt",
        "-s",
        help="Override the default system prompt",
        rich_help_panel="System & Context",
    ),
    append_system_prompt: str | None = typer.Option(
        None,
        "--append-system-prompt",
        help="Append text to the default system prompt",
        rich_help_panel="System & Context",
    ),
    settings_file: str | None = typer.Option(
        None,
        "--settings",
        help="Path to a JSON settings file or inline JSON string",
        rich_help_panel="System & Context",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Anthropic-compatible API base URL",
        rich_help_panel="System & Context",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        "-k",
        help="API key (overrides config and environment)",
        rich_help_panel="System & Context",
    ),
    bare: bool = typer.Option(
        False,
        "--bare",
        help="Minimal mode: skip hooks, plugins, MCP, and auto-discovery",
        rich_help_panel="System & Context",
    ),
    # --- Advanced ---
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug logging",
        rich_help_panel="Advanced",
    ),
    mcp_config: Optional[list[str]] = typer.Option(
        None,
        "--mcp-config",
        help="Load MCP servers from JSON files or strings",
        rich_help_panel="Advanced",
    ),
    cwd: str = typer.Option(
        str(Path.cwd()),
        "--cwd",
        help="Working directory for the session",
        hidden=True,
    ),
    backend_only: bool = typer.Option(
        False,
        "--backend-only",
        help="Run the structured backend host for the React terminal UI",
        hidden=True,
    ),
    stream_deltas: bool = typer.Option(
        False,
        "--stream-deltas",
        help="Enable streaming output (AssistantTextDelta) in backend-only mode",
        hidden=True,
    ),
    agent_session: str | None = typer.Option(
        None,
        "--agent-session",
        help="Internal redirect for agent file-based stdio interception",
        hidden=True,
    ),
    agent_verbose: bool = typer.Option(
        False,
        "--agent-verbose",
        help="Internal logging redirect for agent debug sessions",
        hidden=True,
    ),
) -> None:
    """Start an interactive session or run a single prompt."""
    if ctx.invoked_subcommand is not None:
        return

    import asyncio

    if dangerously_skip_permissions:
        permission_mode = "full_auto"

    # Resolve debug output: -D flag defaults to "debug.log", --debug-output overrides
    if debug_flag and not debug_output:
        debug_output = "debug.log"

    if agent_session is not None:
        from openharness.agent_debug import apply_agent_session_io
        apply_agent_session_io(agent_session, verbose=agent_verbose)
        backend_only = True
        stream_deltas = False  # Suppress typing stream for tests

    from openharness.ui.app import run_print_mode, run_repl

    if print_mode is not None:
        prompt = print_mode.strip()
        if not prompt:
            print("Error: -p/--print requires a prompt value, e.g. -p 'your prompt'", file=sys.stderr)
            raise typer.Exit(1)
        asyncio.run(
            run_print_mode(
                prompt=prompt,
                output_format=output_format or "text",
                cwd=cwd,
                model=model,
                base_url=base_url,
                system_prompt=system_prompt,
                append_system_prompt=append_system_prompt,
                api_key=api_key,
                permission_mode=permission_mode,
                max_turns=max_turns,
                debug_output=debug_output,
            )
        )
        return

    asyncio.run(
        run_repl(
            prompt=None,
            cwd=cwd,
            model=model,
            backend_only=backend_only,
            stream_deltas=stream_deltas,
            base_url=base_url,
            system_prompt=system_prompt,
            debug_output=debug_output,
        )
    )
