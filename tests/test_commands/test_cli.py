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

    def fake_run_task(task_name, argv, **kwargs):
        captured["task_name"] = task_name
        captured["argv"] = argv
        captured["kwargs"] = kwargs
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
        "kwargs": {
            "model": None,
            "base_url": None,
            "api_key": None,
            "api_format": None,
        },
    }


def test_task_dispatch_forwards_treecode_model_args(monkeypatch):
    runner = CliRunner()
    captured = {}

    def fake_run_task(task_name, argv, **kwargs):
        captured["task_name"] = task_name
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(cli, "_run_task", fake_run_task)

    result = runner.invoke(
        app,
        [
            "--model",
            "glm",
            "--api-format",
            "openai",
            "--base-url",
            "http://localhost:8000/v1",
            "--api-key",
            "EMPTY",
            "--task",
            "uniopbench",
            "--operators",
            "activation/relu",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "task_name": "uniopbench",
        "argv": ["--operators", "activation/relu"],
        "kwargs": {
            "model": "glm",
            "base_url": "http://localhost:8000/v1",
            "api_key": "EMPTY",
            "api_format": "openai",
        },
    }
