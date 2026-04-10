"""One-line usage strings and /help topic text for slash commands.

Bash/zsh-style UX: the TUI shows ``usage`` while you type a prefix; ``/help <name>``
mirrors ``man``/``--help`` for a single command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from treecode.commands.registry import CommandRegistry, SlashCommand

# Optional syntax hints for non-trivial commands. Missing keys default to f"/{name}".
SLASH_USAGE: dict[str, str] = {
    "help": "/help [command]",
    "summary": "/summary [MAX_MESSAGES]",
    "compact": "/compact [PRESERVE_RECENT]",
    # Mirrors _memory_handler Usage: line (no "search" subcommand).
    "memory": "/memory [list|show NAME|add TITLE :: CONTENT|remove NAME]",
    "resume": "/resume [SESSION_ID]",
    "session": "/session [show|ls|path|tag NAME|clear]",
    "export": "/export [path]",
    "share": "/share",
    "copy": "/copy [text]",
    "tag": "/tag <name>",
    "rewind": "/rewind [turns]",
    "files": "/files [path]",
    "init": "/init",
    "bridge": "/bridge [show|encode|decode|sdk|spawn|list|output|stop …]",
    "login": "/login [API_KEY]",
    "skills": "/skills [NAME]",
    "config": "/config [show|set KEY VALUE]",
    "mcp": "/mcp",
    "plugin": "/plugin [list|enable|disable|install|uninstall …]",
    "permissions": "/permissions [show|set MODE]",
    "plan": "/plan [on|off]",
    "fast": "/fast [show|on|off|toggle]",
    "effort": "/effort [show|low|medium|high]",
    "passes": "/passes [show|COUNT]",
    "model": "/model [show|set MODEL]",
    "theme": "/theme [show|set THEME]",
    "output-style": "/output-style [show|list|set NAME]",
    "commit": "/commit [message]",
    "issue": "/issue [text]",
    "pr_comments": "/pr_comments [text]",
    "agents": "/agents [help|list|select ...]",
    "agent-defs": "/agent-defs [list|show|init …|path]",
    "execute": "/execute <file>",
    "gather": "/gather [--spec …] [--gather-id …] [--request …] [target] [request]",
    "spawn": "/spawn <profile> <name> <description> [under <agent_id>]",
    "tasks": "/tasks [list|cancel …]",
    "set-max-turns": "/set-max-turns [N]",
}

# Extra paragraphs for /help <name> (optional).
SLASH_TOPIC_EXTRA: dict[str, str] = {
    "help": "Examples: /help memory   /help gather",
    "memory": "With no subcommand, prints the memory directory and MEMORY.md entrypoint.",
    "gather": "Omit target to fan out to children; use --spec for named gather specs.",
}


def slash_usage_line(name: str) -> str:
    return SLASH_USAGE.get(name, f"/{name}")


def catalog_dicts(commands: list["SlashCommand"]) -> list[dict[str, str]]:
    """Payload for React/Web: one object per command."""
    out: list[dict[str, str]] = []
    for cmd in commands:
        usage = slash_usage_line(cmd.name)
        out.append(
            {
                "name": cmd.name,
                "prefix": f"/{cmd.name}",
                "description": cmd.description,
                "usage": usage,
            }
        )
    return out


def format_help_list(registry: "CommandRegistry") -> str:
    """Compact list for /help with no args."""
    lines = [
        "Slash commands — type `/help <command>` for syntax (e.g. `/help memory`).",
        "In the TUI: type `/` for completion; Tab completes the selection; ↑↓ recall input history.",
        "",
    ]
    for cmd in sorted(registry.list_commands(), key=lambda c: c.name):
        usage = slash_usage_line(cmd.name)
        lines.append(f"  {usage:<42} {cmd.description}")
    return "\n".join(lines)


def format_help_topic(registry: "CommandRegistry", topic: str) -> str | None:
    """Multi-line help for /help <topic>, or None if unknown."""
    raw = topic.strip().lstrip("/")
    if not raw:
        return None
    by_name = {c.name: c for c in registry.list_commands()}
    if raw in by_name:
        return _one_topic(by_name[raw])
    matches = [c for c in registry.list_commands() if c.name.startswith(raw)]
    if len(matches) == 1:
        return _one_topic(matches[0])
    if len(matches) > 1:
        names = ", ".join(f"/{m.name}" for m in sorted(matches, key=lambda c: c.name))
        return f'Ambiguous topic "{raw}". Matches: {names}'
    return None


def _one_topic(cmd: "SlashCommand") -> str:
    usage = slash_usage_line(cmd.name)
    extra = SLASH_TOPIC_EXTRA.get(cmd.name, "")
    parts = [
        f"/{cmd.name}",
        "",
        cmd.description,
        "",
        f"Syntax: {usage}",
    ]
    if extra:
        parts.extend(["", extra])
    return "\n".join(parts).rstrip()
