"""Plugin discovery and loading."""

from __future__ import annotations

import json
from pathlib import Path

from treecode.config.paths import get_config_dir
from treecode.plugins.schemas import PluginManifest
from treecode.plugins.types import LoadedPlugin
from treecode.skills.loader import _parse_skill_markdown
from treecode.skills.types import SkillDefinition


def get_user_plugins_dir() -> Path:
    """Return the user plugin directory."""
    path = get_config_dir() / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_plugins_dir(cwd: str | Path) -> Path:
    """Return the project plugin directory."""
    path = Path(cwd).resolve() / ".treecode" / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_manifest(plugin_dir: Path) -> Path | None:
    """Find plugin.json in standard or .claude-plugin/ locations."""
    for candidate in [
        plugin_dir / "plugin.json",
        plugin_dir / ".claude-plugin" / "plugin.json",
    ]:
        if candidate.exists():
            return candidate
    return None


def _discover_claude_code_plugins() -> list[Path]:
    """Discover plugins installed via Claude Code (~/.claude/plugins/cache/)."""
    installed_json = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    if not installed_json.exists():
        return []
    try:
        data = json.loads(installed_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    paths: list[Path] = []
    for _key, installs in data.get("plugins", {}).items():
        if not isinstance(installs, list):
            continue
        for entry in installs:
            install_path = entry.get("installPath")
            if not install_path:
                continue
            p = Path(install_path)
            if p.is_dir() and _find_manifest(p) is not None:
                paths.append(p)
    return sorted(set(paths))


def discover_plugin_paths(cwd: str | Path) -> list[Path]:
    """Find plugin directories from user, project, and Claude Code locations."""
    roots = [get_user_plugins_dir(), get_project_plugins_dir(cwd)]
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.iterdir()):
            if path.is_dir() and _find_manifest(path) is not None:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    paths.append(path)
    for path in _discover_claude_code_plugins():
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(path)
    return paths


def load_plugins(settings, cwd: str | Path) -> list[LoadedPlugin]:
    """Load plugins from disk."""
    plugins: list[LoadedPlugin] = []
    for path in discover_plugin_paths(cwd):
        plugin = load_plugin(path, settings.enabled_plugins)
        if plugin is not None:
            plugins.append(plugin)
    return plugins


def load_plugin(path: Path, enabled_plugins: dict[str, bool]) -> LoadedPlugin | None:
    """Load one plugin directory."""
    manifest_path = _find_manifest(path)
    if manifest_path is None:
        return None
    try:
        manifest = PluginManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    enabled = enabled_plugins.get(manifest.name, manifest.enabled_by_default)

    # Discover skills from multiple locations
    skills = _load_plugin_skills(path / manifest.skills_dir)

    # Discover commands from plugin commands/ directory
    commands_dir = path / "commands"
    if commands_dir.exists():
        skills.extend(_load_plugin_skills(commands_dir))

    # Discover agents from plugin agents/ directory
    agents_dir = path / "agents"
    if agents_dir.exists():
        skills.extend(_load_plugin_skills(agents_dir))

    # Discover hooks from hooks/ dir or root hooks.json
    hooks = _load_plugin_hooks(path / manifest.hooks_file)
    hooks_dir_file = path / "hooks" / "hooks.json"
    if not hooks and hooks_dir_file.exists():
        hooks = _load_plugin_hooks_structured(hooks_dir_file, path)

    mcp = _load_plugin_mcp(path / manifest.mcp_file)
    mcp_json = path / ".mcp.json"
    if not mcp and mcp_json.exists():
        mcp = _load_plugin_mcp(mcp_json)

    return LoadedPlugin(
        manifest=manifest,
        path=path,
        enabled=enabled,
        skills=skills,
        hooks=hooks,
        mcp_servers=mcp,
        commands=[s for s in skills if s.source == "plugin"],
    )


def _load_plugin_skills(path: Path) -> list[SkillDefinition]:
    if not path.exists():
        return []
    skills: list[SkillDefinition] = []
    for skill_path in sorted(path.glob("*.md")):
        content = skill_path.read_text(encoding="utf-8")
        name, description = _parse_skill_markdown(skill_path.stem, content)
        skills.append(
            SkillDefinition(
                name=name,
                description=description,
                content=content,
                source="plugin",
                path=str(skill_path),
            )
        )
    return skills


def _load_plugin_hooks(path: Path) -> dict[str, list]:
    if not path.exists():
        return {}
    from treecode.hooks.schemas import (
        AgentHookDefinition,
        CommandHookDefinition,
        HttpHookDefinition,
        PromptHookDefinition,
    )

    raw = json.loads(path.read_text(encoding="utf-8"))
    parsed: dict[str, list] = {}
    for event, hooks in raw.items():
        parsed[event] = []
        for hook in hooks:
            hook_type = hook.get("type")
            if hook_type == "command":
                parsed[event].append(CommandHookDefinition.model_validate(hook))
            elif hook_type == "prompt":
                parsed[event].append(PromptHookDefinition.model_validate(hook))
            elif hook_type == "http":
                parsed[event].append(HttpHookDefinition.model_validate(hook))
            elif hook_type == "agent":
                parsed[event].append(AgentHookDefinition.model_validate(hook))
    return parsed


def _load_plugin_hooks_structured(path: Path, plugin_root: Path) -> dict[str, list]:
    """Load hooks from structured hooks.json format."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    hooks_data = raw.get("hooks", raw)
    if not isinstance(hooks_data, dict):
        return {}
    parsed: dict[str, list] = {}
    for event, entries in hooks_data.items():
        if not isinstance(entries, list):
            continue
        parsed[event] = []
        for entry in entries:
            hook_list = entry.get("hooks", [])
            matcher = entry.get("matcher", "")
            for hook in hook_list:
                # Replace ${CLAUDE_PLUGIN_ROOT} with actual path
                cmd = hook.get("command", "")
                cmd = cmd.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))
                parsed[event].append({
                    "type": hook.get("type", "command"),
                    "command": cmd,
                    "matcher": matcher,
                    "timeout": hook.get("timeout"),
                })
    return parsed


def _load_plugin_mcp(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    from treecode.mcp.types import McpJsonConfig, McpStdioServerConfig

    raw = json.loads(path.read_text(encoding="utf-8"))

    # TreeCode format: {"mcpServers": {"name": {...}}}
    if "mcpServers" in raw:
        parsed = McpJsonConfig.model_validate(raw)
        return parsed.mcpServers

    # Claude Code flat format: {"name": {"command": "...", "args": [...]}}
    servers: dict[str, object] = {}
    for name, config in raw.items():
        if isinstance(config, dict) and "command" in config:
            servers[name] = McpStdioServerConfig.model_validate(config)
    return servers
