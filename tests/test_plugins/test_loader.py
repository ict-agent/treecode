"""Tests for plugin loading."""

from __future__ import annotations

import json
from pathlib import Path

from treecode.config.settings import Settings
from treecode.hooks.loader import load_hook_registry
from treecode.mcp.types import McpStdioServerConfig
from treecode.plugins import load_plugins
from treecode.plugins.loader import _discover_claude_code_plugins, _load_plugin_mcp
from treecode.skills import load_skill_registry


def _write_plugin(root: Path) -> None:
    plugin_dir = root / "example-plugin"
    (plugin_dir / "skills").mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "example",
                "version": "1.0.0",
                "description": "Example plugin",
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "skills" / "deploy.md").write_text(
        "# Deploy\nDeploy with care\n",
        encoding="utf-8",
    )
    (plugin_dir / "hooks.json").write_text(
        json.dumps(
            {
                "session_start": [
                    {"type": "command", "command": "printf start"}
                ]
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "demo": {"type": "stdio", "command": "python", "args": ["demo.py"]}
                }
            }
        ),
        encoding="utf-8",
    )


def test_load_plugins_from_project_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("TREECODE_CONFIG_DIR", str(tmp_path / "config"))
    project = tmp_path / "repo"
    plugins_root = project / ".treecode" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_plugin(plugins_root)

    plugins = load_plugins(Settings(), project)

    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest.name == "example"
    assert plugin.skills[0].name == "Deploy"
    assert "session_start" in plugin.hooks
    assert "demo" in plugin.mcp_servers


def test_plugin_skills_and_hooks_are_merged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("TREECODE_CONFIG_DIR", str(tmp_path / "config"))
    project = tmp_path / "repo"
    plugins_root = project / ".treecode" / "plugins"
    plugins_root.mkdir(parents=True)
    _write_plugin(plugins_root)

    skills = load_skill_registry(project).list_skills()
    assert any(skill.name == "Deploy" and skill.source == "plugin" for skill in skills)

    plugins = load_plugins(Settings(), project)
    hooks = load_hook_registry(Settings(), plugins)
    assert "session_start" in hooks.summary()


def test_load_plugin_mcp_claude_code_flat_format(tmp_path: Path):
    """Claude Code plugins use flat format: {"name": {"command": "...", "args": [...]}}."""
    mcp_json = tmp_path / ".mcp.json"
    mcp_json.write_text(
        json.dumps(
            {
                "serena": {
                    "command": "uvx",
                    "args": ["--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server"],
                }
            }
        ),
        encoding="utf-8",
    )

    servers = _load_plugin_mcp(mcp_json)

    assert "serena" in servers
    config = servers["serena"]
    assert isinstance(config, McpStdioServerConfig)
    assert config.command == "uvx"
    assert config.type == "stdio"


def test_load_plugin_with_claude_plugin_dir_and_flat_mcp(tmp_path: Path, monkeypatch):
    """End-to-end: .claude-plugin/plugin.json + flat .mcp.json loads correctly."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("TREECODE_CONFIG_DIR", str(tmp_path / "config"))
    project = tmp_path / "repo"
    plugins_root = project / ".treecode" / "plugins"
    plugin_dir = plugins_root / "serena"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "serena",
                "description": "Semantic code analysis MCP server",
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "serena": {
                    "command": "uvx",
                    "args": ["--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server"],
                }
            }
        ),
        encoding="utf-8",
    )

    plugins = load_plugins(Settings(), project)

    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.manifest.name == "serena"
    assert "serena" in plugin.mcp_servers
    config = plugin.mcp_servers["serena"]
    assert isinstance(config, McpStdioServerConfig)
    assert config.command == "uvx"


def _write_claude_code_plugin(home: Path) -> Path:
    """Create a fake Claude Code plugin installation."""
    plugin_dir = home / ".claude" / "plugins" / "cache" / "official" / "serena" / "unknown"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "serena", "description": "Semantic code analysis"}),
        encoding="utf-8",
    )
    (plugin_dir / ".mcp.json").write_text(
        json.dumps({"serena": {"command": "uvx", "args": ["serena", "start-mcp-server"]}}),
        encoding="utf-8",
    )
    installed = home / ".claude" / "plugins" / "installed_plugins.json"
    installed.write_text(
        json.dumps({
            "version": 2,
            "plugins": {
                "serena@official": [{"scope": "user", "installPath": str(plugin_dir)}],
            },
        }),
        encoding="utf-8",
    )
    return plugin_dir


def test_discover_claude_code_plugins(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    plugin_dir = _write_claude_code_plugin(tmp_path)

    paths = _discover_claude_code_plugins()

    assert len(paths) == 1
    assert paths[0] == plugin_dir


def test_load_plugins_includes_claude_code(tmp_path: Path, monkeypatch):
    """TreeCode should auto-discover plugins installed via Claude Code."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("TREECODE_CONFIG_DIR", str(tmp_path / "tc-config"))
    _write_claude_code_plugin(tmp_path)
    project = tmp_path / "repo"
    project.mkdir()

    plugins = load_plugins(Settings(), project)

    assert any(p.manifest.name == "serena" for p in plugins)
    serena = [p for p in plugins if p.manifest.name == "serena"][0]
    assert "serena" in serena.mcp_servers
