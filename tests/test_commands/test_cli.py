"""CLI smoke tests."""

import openharness.cli as cli
from typer.testing import CliRunner

app = cli.app


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Oh my Harness!" in result.output


def test_dangerously_skip_permissions_passes_full_auto_to_run_repl(monkeypatch):
    runner = CliRunner()
    captured = {}

    async def fake_run_repl(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("openharness.ui.app.run_repl", fake_run_repl)

    result = runner.invoke(app, ["--dangerously-skip-permissions"])

    assert result.exit_code == 0
    assert captured["permission_mode"] == "full_auto"
