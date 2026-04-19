"""CLI smoke tests."""

import treecode.cli as cli
from typer.testing import CliRunner

app = cli.app


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "TreeCode" in result.output


def test_dangerously_skip_permissions_passes_full_auto_to_run_repl(monkeypatch):
    runner = CliRunner()
    captured = {}

    async def fake_run_repl(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("treecode.ui.app.run_repl", fake_run_repl)

    result = runner.invoke(app, ["--dangerously-skip-permissions"])

    assert result.exit_code == 0
    assert captured["permission_mode"] == "full_auto"


def test_task_dispatch_forwards_unknown_args(monkeypatch):
    runner = CliRunner()
    captured = {}

    def fake_run_task(task_name, argv):
        captured["task_name"] = task_name
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "_run_task", fake_run_task)

    result = runner.invoke(
        app,
        ["--task", "uniopbench", "--operators", "norm/rmsnorm", "optimize", "--rounds", "3"],
    )

    assert result.exit_code == 0
    assert captured == {
        "task_name": "uniopbench",
        "argv": ["--operators", "norm/rmsnorm", "optimize", "--rounds", "3"],
    }
