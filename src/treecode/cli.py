"""CLI entry point using typer."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

__version__ = "0.1.1"


def _version_callback(value: bool) -> None:
    if value:
        print(f"TreeCode {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="treecode",
    help=(
        "TreeCode — tree-based multi-agent coding harness.\n\n"
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
agent_app = typer.Typer(name="agent", help="Swarm agent management utilities")
agent_debug_app = typer.Typer(name="agent-debug", help="External agent E2E debugging utilities")
cron_app = typer.Typer(name="cron", help="Manage cron scheduler and jobs")
swarm_debug_app = typer.Typer(name="swarm-debug", help="Run the web swarm debugger")
swarm_console_app = typer.Typer(name="swarm-console", help="Run the WebSocket backend for the multi-agent web console")

app.add_typer(mcp_app)
app.add_typer(plugin_app)
app.add_typer(auth_app)
app.add_typer(agent_app)
app.add_typer(agent_debug_app)
app.add_typer(cron_app)
app.add_typer(swarm_debug_app)
app.add_typer(swarm_console_app)


# ---- mcp subcommands ----

@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers."""
    from treecode.config import load_settings
    from treecode.mcp.config import load_mcp_server_configs
    from treecode.plugins import load_plugins

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
    from treecode.config import load_settings, save_settings

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
    from treecode.config import load_settings, save_settings

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
    from treecode.config import load_settings
    from treecode.plugins import load_plugins

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
    from treecode.plugins.installer import install_plugin_from_path

    result = install_plugin_from_path(source)
    print(f"Installed plugin: {result}")


@plugin_app.command("uninstall")
def plugin_uninstall(
    name: str = typer.Argument(..., help="Plugin name to uninstall"),
) -> None:
    """Uninstall a plugin."""
    from treecode.plugins.installer import uninstall_plugin

    uninstall_plugin(name)
    print(f"Uninstalled plugin: {name}")


# ---- cron subcommands ----

@cron_app.command("start")
def cron_start() -> None:
    """Start the cron scheduler daemon."""
    from treecode.services.cron_scheduler import is_scheduler_running, start_daemon

    if is_scheduler_running():
        print("Cron scheduler is already running.")
        return
    pid = start_daemon()
    print(f"Cron scheduler started (pid={pid})")


@cron_app.command("stop")
def cron_stop() -> None:
    """Stop the cron scheduler daemon."""
    from treecode.services.cron_scheduler import stop_scheduler

    if stop_scheduler():
        print("Cron scheduler stopped.")
    else:
        print("Cron scheduler is not running.")


@cron_app.command("status")
def cron_status_cmd() -> None:
    """Show cron scheduler status and job summary."""
    from treecode.services.cron_scheduler import scheduler_status

    status = scheduler_status()
    state = "running" if status["running"] else "stopped"
    print(f"Scheduler: {state}" + (f" (pid={status['pid']})" if status["pid"] else ""))
    print(f"Jobs:      {status['enabled_jobs']} enabled / {status['total_jobs']} total")
    print(f"Log:       {status['log_file']}")


@cron_app.command("list")
def cron_list_cmd() -> None:
    """List all registered cron jobs with schedule and status."""
    from treecode.services.cron import load_cron_jobs

    jobs = load_cron_jobs()
    if not jobs:
        print("No cron jobs configured.")
        return
    for job in jobs:
        enabled = "on " if job.get("enabled", True) else "off"
        last = job.get("last_run", "never")
        if last != "never":
            last = last[:19]  # trim to readable datetime
        last_status = job.get("last_status", "")
        status_indicator = f" [{last_status}]" if last_status else ""
        print(f"  [{enabled}] {job['name']}  {job.get('schedule', '?')}")
        print(f"        cmd: {job['command']}")
        print(f"        last: {last}{status_indicator}  next: {job.get('next_run', 'n/a')[:19]}")


@cron_app.command("toggle")
def cron_toggle_cmd(
    name: str = typer.Argument(..., help="Cron job name"),
    enabled: bool = typer.Argument(..., help="true to enable, false to disable"),
) -> None:
    """Enable or disable a cron job."""
    from treecode.services.cron import set_job_enabled

    if not set_job_enabled(name, enabled):
        print(f"Cron job not found: {name}")
        raise typer.Exit(1)
    state = "enabled" if enabled else "disabled"
    print(f"Cron job '{name}' is now {state}")


@cron_app.command("history")
def cron_history_cmd(
    name: str | None = typer.Argument(None, help="Filter by job name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of entries"),
) -> None:
    """Show cron execution history."""
    from treecode.services.cron_scheduler import load_history

    entries = load_history(limit=limit, job_name=name)
    if not entries:
        print("No execution history.")
        return
    for entry in entries:
        ts = entry.get("started_at", "?")[:19]
        status = entry.get("status", "?")
        rc = entry.get("returncode", "?")
        print(f"  {ts}  {entry.get('name', '?')}  {status} (rc={rc})")
        stderr = entry.get("stderr", "").strip()
        if stderr and status != "success":
            for line in stderr.splitlines()[:3]:
                print(f"    stderr: {line}")


@cron_app.command("logs")
def cron_logs_cmd(
    lines: int = typer.Option(30, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """Show recent cron scheduler log output."""
    from treecode.config.paths import get_logs_dir

    log_path = get_logs_dir() / "cron_scheduler.log"
    if not log_path.exists():
        print("No scheduler log found. Start the scheduler with: treecode cron start")
        return
    content = log_path.read_text(encoding="utf-8", errors="replace")
    tail = content.splitlines()[-lines:]
    for line in tail:
        print(line)


# ---- auth subcommands ----

@auth_app.command("status")
def auth_status_cmd() -> None:
    """Show authentication status."""
    from treecode.api.provider import auth_status, detect_provider
    from treecode.config import load_settings

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
    from treecode.config import load_settings, save_settings

    if not api_key:
        api_key = typer.prompt("Enter your API key", hide_input=True)
    settings = load_settings()
    settings.api_key = api_key
    save_settings(settings)
    print("API key saved.")


@auth_app.command("logout")
def auth_logout() -> None:
    """Remove stored authentication."""
    from treecode.config import load_settings, save_settings

    settings = load_settings()
    settings.api_key = None
    save_settings(settings)
    print("Authentication cleared.")


# ---- agent subcommands ----

@agent_app.command("email-to-inbox")
def agent_email_to_inbox(
    team: str = typer.Argument(..., help="Team name the agent belongs to"),
    agent_id: str = typer.Argument(..., help="Agent ID to send message to"),
    message: str = typer.Argument(..., help="Message text content to send to the agent"),
    payload: str = typer.Option(
        None,
        "--payload",
        "-p",
        help="Additional JSON payload to include with the message (string or file path)",
    ),
) -> None:
    """Send a message directly to a swarm agent's inbox.

    Messages are written to ~/.treecode/teams/<team>/agents/<agent_id>/inbox/
    as JSON files. The agent will process the message on its next polling cycle.

    Example:
        treecode agent email-to-inbox myteam agent-001 "Please check the logs"
        treecode agent email-to-inbox myteam agent-001 "Run analysis" --payload '{"task": "analyze"}'
    """
    import time
    import uuid

    from treecode.swarm.mailbox import (
        MailboxMessage,
        get_agent_mailbox_dir,
    )

    # Parse payload
    extra_payload: dict = {}
    if payload is not None:
        try:
            # Try parsing as JSON string first
            extra_payload = json.loads(payload)
        except json.JSONDecodeError:
            # If that fails, treat as a file path
            path = Path(payload)
            if path.exists():
                extra_payload = json.loads(path.read_text(encoding="utf-8"))
            else:
                print(f"Error: Could not parse payload as JSON or find file: {payload}", file=sys.stderr)
                raise typer.Exit(1)

    # Create the MailboxMessage
    message_id = str(uuid.uuid4())
    mail_message = MailboxMessage(
        id=message_id,
        type="user_message",
        sender="cli",
        recipient=agent_id,
        payload={
            "text": message,
            **extra_payload,
        },
        timestamp=time.time(),
    )

    # Write to the agent's inbox
    mailbox_dir = get_agent_mailbox_dir(team, agent_id)
    filename = f"{mail_message.timestamp:.6f}_{mail_message.id}.json"
    final_path = mailbox_dir / filename

    # Write atomically
    tmp_path = mailbox_dir / f"{filename}.tmp"
    tmp_path.write_text(json.dumps(mail_message.to_dict(), indent=2), encoding="utf-8")
    tmp_path.replace(final_path)

    print(f"Message sent to {team}/{agent_id}")
    print(f"  File: {final_path}")


# ---- agent-debug subcommands ----

@agent_debug_app.command("start")
def debug_start(
    session_id: str = typer.Argument(..., help="Unique identifier for the test session"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Extract raw LLM prompt payloads into pretty_output_verbose.txt"),
) -> None:
    """Start an TreeCode backend daemon in the background for agent debugging."""
    from treecode.agent_debug import start_debug_session
    start_debug_session(session_id, verbose=verbose)


@agent_debug_app.command("send")
def debug_send(
    session_id: str = typer.Argument(..., help="The active session identifier"),
    message: str = typer.Argument(..., help="Prompt text or raw raw JSON string"),
) -> None:
    """Submit a query to an active background session and synchronously wait for JSON completion."""
    from treecode.agent_debug import send_debug_message
    send_debug_message(session_id, message)


@agent_debug_app.command("stop")
def debug_stop(
    session_id: str = typer.Argument(..., help="Identifier of the session to terminate"),
) -> None:
    """Silently murder the background debugging process and clean context."""
    from treecode.agent_debug import stop_debug_session
    stop_debug_session(session_id)


@swarm_debug_app.command("start")
def swarm_debug_start(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the debugger server to"),
    port: int = typer.Option(8765, "--port", help="Port to bind the debugger server to"),
) -> None:
    """Start the browser-based swarm debugger."""
    from treecode.swarm.debug_server import SwarmDebugServer
    from treecode.swarm.debugger import create_default_swarm_debugger_service

    server = SwarmDebugServer(
        service=create_default_swarm_debugger_service(),
        host=host,
        port=port,
    )
    server.start()
    print(f"Swarm debugger running at {server.base_url}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            import time as _time

            _time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("Swarm debugger stopped.")


@swarm_console_app.command("start")
def swarm_console_start(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the WebSocket console backend to"),
    port: int = typer.Option(8766, "--port", help="Port to bind the WebSocket console backend to"),
) -> None:
    """Start the WebSocket backend for the multi-agent web console."""
    import asyncio
    import os

    from treecode.swarm.console_ws import SwarmConsoleWsServer
    from treecode.swarm.debugger import create_default_swarm_debugger_service

    if host not in {"127.0.0.1", "localhost"} and os.environ.get("TREECODE_ALLOW_REMOTE_SWARM_CONSOLE") != "1":
        print(
            "Refusing to bind swarm-console outside localhost without explicit opt-in.\n"
            "Set TREECODE_ALLOW_REMOTE_SWARM_CONSOLE=1 if you really want remote access."
        )
        raise typer.Exit(1)

    async def _run() -> None:
        server = SwarmConsoleWsServer(
            service=create_default_swarm_debugger_service(cwd=Path.cwd()),
            host=host,
            port=port,
        )
        await server.start()
        print(f"Swarm console WebSocket running at {server.ws_url}")
        print("Use frontend/terminal with VITE_SWARM_CONSOLE_WS_URL pointed here.")
        try:
            while True:
                await asyncio.sleep(1)
        finally:
            await server.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("Swarm console stopped.")


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
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
    api_format: str | None = typer.Option(
        None,
        "--api-format",
        help="API format: 'anthropic' (default) or 'openai' (for DashScope, GitHub Models, etc.)",
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
    open_web_console: bool = typer.Option(
        False,
        "--open-web-console",
        help="Open browser to swarm web console (set TREECODE_WEB_CONSOLE_BASE if not using Vite default)",
        rich_help_panel="Session",
    ),
    web_console_base: Optional[str] = typer.Option(
        None,
        "--web-console-base",
        envvar="TREECODE_WEB_CONSOLE_BASE",
        help="Base URL of the Vite dev server (default http://127.0.0.1:5173)",
        rich_help_panel="Session",
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
    import logging

    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
            stream=sys.stderr,
        )
        logging.getLogger("treecode").setLevel(logging.DEBUG)
    elif os.environ.get("TREECODE_LOG_LEVEL"):
        lvl = getattr(logging, os.environ["TREECODE_LOG_LEVEL"].upper(), logging.WARNING)
        logging.basicConfig(level=lvl, format="%(asctime)s [%(name)s] %(levelname)s %(message)s", stream=sys.stderr)

    if dangerously_skip_permissions:
        permission_mode = "full_auto"

    if open_web_console:
        os.environ["TREECODE_OPEN_WEB_CONSOLE"] = "1"
    if web_console_base:
        os.environ["TREECODE_WEB_CONSOLE_BASE"] = web_console_base

    # Resolve debug output: -D flag defaults to "debug.log", --debug-output overrides
    if debug_flag and not debug_output:
        debug_output = "debug.log"

    if agent_session is not None:
        from treecode.agent_debug import apply_agent_session_io
        apply_agent_session_io(agent_session, verbose=agent_verbose)
        backend_only = True
        stream_deltas = False  # Suppress typing stream for tests

    from treecode.ui.app import run_print_mode, run_repl

    # Handle --continue and --resume flags
    if continue_session or resume is not None:
        from treecode.services.session_storage import (
            list_session_snapshots,
            load_session_by_id,
            load_session_snapshot,
        )

        session_data = None
        if continue_session:
            session_data = load_session_snapshot(cwd)
            if session_data is None:
                print("No previous session found in this directory.", file=sys.stderr)
                raise typer.Exit(1)
            print(f"Continuing session: {session_data.get('summary', '(untitled)')[:60]}")
        elif resume == "" or resume is None:
            # --resume with no value: show session picker
            sessions = list_session_snapshots(cwd, limit=10)
            if not sessions:
                print("No saved sessions found.", file=sys.stderr)
                raise typer.Exit(1)
            print("Saved sessions:")
            for i, s in enumerate(sessions, 1):
                print(f"  {i}. [{s['session_id']}] {s.get('summary', '?')[:50]} ({s['message_count']} msgs)")
            choice = typer.prompt("Enter session number or ID")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(sessions):
                    session_data = load_session_by_id(cwd, sessions[idx]["session_id"])
                else:
                    print("Invalid selection.", file=sys.stderr)
                    raise typer.Exit(1)
            except ValueError:
                session_data = load_session_by_id(cwd, choice)
            if session_data is None:
                print(f"Session not found: {choice}", file=sys.stderr)
                raise typer.Exit(1)
        else:
            session_data = load_session_by_id(cwd, resume)
            if session_data is None:
                print(f"Session not found: {resume}", file=sys.stderr)
                raise typer.Exit(1)

        # Pass restored session to the REPL
        asyncio.run(
            run_repl(
                prompt=None,
                cwd=cwd,
                model=session_data.get("model") or model,
                backend_only=backend_only,
                base_url=base_url,
                system_prompt=session_data.get("system_prompt") or system_prompt,
                api_key=api_key,
                restore_messages=session_data.get("messages"),
                permission_mode=permission_mode,
                api_format=api_format,
            )
        )
        return

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
                api_format=api_format,
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
            api_key=api_key,
            api_format=api_format,
            permission_mode=permission_mode,
        )
    )
