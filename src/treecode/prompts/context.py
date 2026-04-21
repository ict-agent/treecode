"""Higher-level system prompt assembly."""

from __future__ import annotations

from pathlib import Path

from treecode.config.paths import get_project_issue_file, get_project_pr_comments_file
from treecode.config.settings import Settings
from treecode.mcp.client import McpClientManager
from treecode.memory import find_relevant_memories, load_memory_prompt
from treecode.output_styles.loader import load_output_styles
from treecode.prompts.claudemd import load_claude_md_prompt
from treecode.prompts.system_prompt import build_system_prompt
from treecode.skills.loader import load_skill_registry


def _build_skills_section(cwd: str | Path) -> str | None:
    """Build a system prompt section listing available skills."""
    registry = load_skill_registry(cwd)
    skills = registry.list_skills()
    if not skills:
        return None
    lines = [
        "# Available Skills",
        "",
        "The following skills are available via the `skill` tool. "
        "When a user's request matches a skill, invoke it with `skill(name=\"<skill_name>\")` "
        "to load detailed instructions before proceeding.",
        "",
    ]
    for skill in skills:
        lines.append(f"- **{skill.name}**: {skill.description}")
    return "\n".join(lines)


def _build_mcp_tools_guide(mcp_manager: McpClientManager | None) -> str | None:
    """Build a system prompt section describing connected MCP servers and their tools."""
    if mcp_manager is None:
        return None
    connected = [s for s in mcp_manager.list_statuses() if s.state == "connected" and s.tools]
    if not connected:
        return None
    lines = [
        "# MCP Server Instructions",
        "",
        "The following MCP servers are connected and provide enhanced capabilities. "
        "When an MCP tool offers a more precise or semantic alternative to a built-in tool, "
        "prefer the MCP tool.",
        "",
    ]
    for status in connected:
        lines.append(f"## {status.name}")
        if status.instructions:
            lines.extend(["", status.instructions, ""])
        else:
            tool_names = [t.name for t in status.tools]
            has_semantic = any(
                t in tool_names
                for t in ("find_symbol", "get_symbols_overview", "find_referencing_symbols")
            )
            if has_semantic:
                lines.extend([
                    "",
                    "This server provides **semantic code analysis** via LSP. Prefer these tools "
                    "over text-based built-in equivalents:",
                    "- `find_symbol` / `get_symbols_overview` over `grep` / `read_file` for code exploration",
                    "- `find_referencing_symbols` over `grep` for finding all usages of a symbol",
                    "- `replace_symbol_body` / `rename_symbol` over `edit_file` for refactoring",
                    "- `search_for_pattern` for flexible regex search across the codebase",
                    "",
                ])
        lines.append("Available tools: " + ", ".join(f"`{t.name}`" for t in status.tools))
        lines.append("")
    return "\n".join(lines)


def build_runtime_system_prompt(
    settings: Settings,
    *,
    cwd: str | Path,
    latest_user_prompt: str | None = None,
    mcp_manager: McpClientManager | None = None,
) -> str:
    """Build the runtime system prompt with project instructions and memory."""
    sections = [build_system_prompt(custom_prompt=settings.system_prompt, cwd=str(cwd))]

    if settings.fast_mode:
        sections.append(
            "# Session Mode\nFast mode is enabled. Prefer concise replies, minimal tool use, and quicker progress over exhaustive exploration."
        )

    # Inject output style instructions
    styles = load_output_styles()
    selected_style = next((s for s in styles if s.name == settings.output_style), None)
    if selected_style and selected_style.name != "default":
        sections.append(f"# Output Style: {selected_style.name.title()}\n{selected_style.content}")

    sections.append(
        "# Reasoning Settings\n"
        f"- Effort: {settings.effort}\n"
        f"- Passes: {settings.passes}\n"
        "Adjust depth and iteration count to match these settings while still completing the task."
    )

    skills_section = _build_skills_section(cwd)
    if skills_section:
        sections.append(skills_section)

    mcp_guide = _build_mcp_tools_guide(mcp_manager)
    if mcp_guide:
        sections.append(mcp_guide)

    claude_md = load_claude_md_prompt(cwd)
    if claude_md:
        sections.append(claude_md)

    for title, path in (
        ("Issue Context", get_project_issue_file(cwd)),
        ("Pull Request Comments", get_project_pr_comments_file(cwd)),
    ):
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                sections.append(f"# {title}\n\n```md\n{content[:12000]}\n```")

    if settings.memory.enabled:
        memory_section = load_memory_prompt(
            cwd,
            max_entrypoint_lines=settings.memory.max_entrypoint_lines,
        )
        if memory_section:
            sections.append(memory_section)

        if latest_user_prompt:
            relevant = find_relevant_memories(
                latest_user_prompt,
                cwd,
                max_results=settings.memory.max_files,
            )
            if relevant:
                lines = ["# Relevant Memories"]
                for header in relevant:
                    content = header.path.read_text(encoding="utf-8", errors="replace").strip()
                    lines.extend(
                        [
                            "",
                            f"## {header.path.name}",
                            "```md",
                            content[:8000],
                            "```",
                        ]
                    )
                sections.append("\n".join(lines))

    return "\n\n".join(section for section in sections if section.strip())
