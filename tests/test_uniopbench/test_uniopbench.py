from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from treecode.api.usage import UsageSnapshot
from treecode.engine.messages import ConversationMessage, TextBlock
from treecode.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(relative_path: str, module_name: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_cli_normalizes_default_run_and_flexible_optimize():
    cli_module = _load_module("task/uniopbench/cli.py", "test_uniopbench_cli_parser")

    assert cli_module._normalize_argv(["treecode", "--operators", "norm/rmsnorm"]) == [
        "run",
        "--operators",
        "norm/rmsnorm",
    ]
    assert cli_module._normalize_argv(
        ["treecode", "--task", "uniopbench", "--operators", "norm/rmsnorm", "optimize", "--rounds", "3"]
    ) == [
        "optimize",
        "--task",
        "uniopbench",
        "--operators",
        "norm/rmsnorm",
        "--rounds",
        "3",
    ]


def test_optimize_parser_accepts_resume():
    cli_module = _load_module("task/uniopbench/cli.py", "test_uniopbench_cli_resume")

    parser = cli_module.build_parser()
    args = parser.parse_args(["optimize", "--resume"])

    assert args.subcommand == "optimize"
    assert args.resume is True


def test_task_config_rejects_legacy_model_settings(tmp_path):
    orchestrator = _load_module(
        "task/uniopbench/orchestrator.py",
        "test_uniopbench_orchestrator_legacy_config",
    )
    config_path = tmp_path / "task.yaml"
    config_path.write_text(
        """
experiment:
  name: bad
  model: old-model
  provider: vllm
operators:
  - activation/relu
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no longer accept model-call settings"):
        orchestrator.load_task_config(config_path)


def test_optimize_requires_resume_for_existing_run(tmp_path, monkeypatch):
    orchestrator = _load_module(
        "task/uniopbench/orchestrator.py",
        "test_uniopbench_orchestrator_existing_run",
    )

    task_config = SimpleNamespace(
        experiment=SimpleNamespace(name="exp"),
        operators=[],
    )
    monkeypatch.setattr(orchestrator, "load_task_config", lambda *args, **kwargs: task_config)
    monkeypatch.setattr(orchestrator, "runs_root", lambda _name: tmp_path)

    run_dir = tmp_path / "resume_run"
    run_dir.mkdir()

    args = SimpleNamespace(
        config=None,
        operators=None,
        no_truncate=False,
        dry_run=False,
        target_speedup=1.0,
        rounds=1,
        max_version=None,
        ref_impl=None,
        run_id="resume_run",
        resume=False,
    )

    with pytest.raises(FileExistsError):
        orchestrator.run_optimize_task(args)


def test_optimize_resume_skips_recorded_operators(tmp_path, monkeypatch):
    orchestrator = _load_module(
        "task/uniopbench/orchestrator.py",
        "test_uniopbench_orchestrator_resume_skip",
    )

    task_config = SimpleNamespace(
        experiment=SimpleNamespace(name="exp"),
        operators=["activation/relu", "conv/depthwiseconv"],
    )
    monkeypatch.setattr(orchestrator, "load_task_config", lambda *args, **kwargs: task_config)
    monkeypatch.setattr(orchestrator, "runs_root", lambda _name: tmp_path)

    source_dir = tmp_path / "operator_source"
    source_dir.mkdir()
    (source_dir / "test.py").write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(orchestrator, "operator_scaffold_dir", lambda _operator: source_dir)
    monkeypatch.setattr(orchestrator, "supports_variants", lambda _path: False)
    monkeypatch.setattr(orchestrator, "build_prompt", lambda *args, **kwargs: ("system", "user"))

    copy_calls: list[Path] = []

    def fake_copy_operator_tree(_src: Path, dst: Path) -> None:
        copy_calls.append(dst)

    monkeypatch.setattr(orchestrator, "copy_operator_tree", fake_copy_operator_tree)

    run_dir = tmp_path / "resume_run"
    run_dir.mkdir()
    summary_path = run_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "operators": {
                    "activation__relu": {
                        "operator": "activation/relu",
                        "status": "passed",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    args = SimpleNamespace(
        config=None,
        operators=None,
        no_truncate=False,
        dry_run=True,
        target_speedup=1.0,
        rounds=1,
        max_version=None,
        ref_impl=None,
        run_id="resume_run",
        resume=True,
    )

    rc = orchestrator.run_optimize_task(args)

    assert rc == 0
    assert copy_calls == [run_dir / "operators" / "conv__depthwiseconv" / "artifact"]

    updated_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert set(updated_summary["operators"]) == {
        "activation__relu",
        "conv__depthwiseconv",
    }
    assert updated_summary["operators"]["activation__relu"]["status"] == "passed"
    assert updated_summary["operators"]["conv__depthwiseconv"]["status"] == "dry_run"


def test_treecode_trajectory_parses_test_results(tmp_path):
    orchestrator = _load_module(
        "task/uniopbench/orchestrator.py",
        "test_uniopbench_orchestrator_trajectory",
    )
    trajectory = tmp_path / "trajectory.log"
    trajectory.write_text(
        """
[USER]
run tests

[TOOL CALL #1: bash]
{"command": "python test.py --no-perf"}

[TOOL RESPONSE #1: bash]
STATUS: PASSED

[TOOL CALL #1: bash]
{"command": "python test.py"}

[TOOL RESPONSE #1: bash]
STATUS: PASSED
Speedup: 1.25x

[TOOL CALL #1: bash]
{"command": "python test.py --variants yaml --no-perf"}

[TOOL RESPONSE #1: bash]
STATUS: PASSED
""",
        encoding="utf-8",
    )

    parsed = orchestrator.parse_agent_test_results(trajectory)

    assert parsed == {
        "verify_passed": True,
        "perf_passed": True,
        "verify_log": "command=python test.py --no-perf\nSTATUS: PASSED",
        "perf_log": "command=python test.py\nSTATUS: PASSED\nSpeedup: 1.25x",
        "variants_passed": True,
        "variants_log": "command=python test.py --variants yaml --no-perf\nSTATUS: PASSED",
    }
    assert orchestrator.parse_all_intermediate_perf_results(trajectory) == [
        {"speedup": 1.25, "perf_log": "command=python test.py\nSTATUS: PASSED\nSpeedup: 1.25x"}
    ]


def test_run_agent_round_uses_treecode_runtime(tmp_path, monkeypatch):
    orchestrator = _load_module(
        "task/uniopbench/orchestrator.py",
        "test_uniopbench_orchestrator_runtime",
    )
    import treecode.ui.runtime as runtime_module

    captured: dict[str, object] = {}

    async def fake_build_runtime(**kwargs):
        captured["build_kwargs"] = kwargs
        query_context = SimpleNamespace(model="test-model", max_tokens=1234)
        engine = SimpleNamespace(
            total_usage=UsageSnapshot(input_tokens=7, output_tokens=11),
            messages=[ConversationMessage.from_user_text("hello")],
            to_query_context=lambda: query_context,
        )
        app_state = SimpleNamespace(
            get=lambda: SimpleNamespace(
                provider="openai-compatible",
                base_url="http://localhost:8000/v1",
            )
        )
        return SimpleNamespace(
            engine=engine,
            app_state=app_state,
            current_settings=lambda: SimpleNamespace(api_format="openai"),
        )

    async def fake_start_runtime(_bundle):
        captured["started"] = True

    async def fake_close_runtime(_bundle):
        captured["closed"] = True

    async def fake_handle_line(_bundle, line, *, print_system, render_event, clear_output):
        captured["line"] = line
        await render_event(AssistantTextDelta(text="working"))
        await render_event(ToolExecutionStarted(tool_name="bash", tool_input={"command": "python test.py"}))
        await render_event(ToolExecutionCompleted(tool_name="bash", output="STATUS: PASSED"))
        await render_event(
            AssistantTurnComplete(
                message=ConversationMessage(
                    role="assistant",
                    content=[TextBlock(text="done")],
                ),
                usage=UsageSnapshot(input_tokens=7, output_tokens=11),
            )
        )

    monkeypatch.setattr(runtime_module, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(runtime_module, "start_runtime", fake_start_runtime)
    monkeypatch.setattr(runtime_module, "close_runtime", fake_close_runtime)
    monkeypatch.setattr(runtime_module, "handle_line", fake_handle_line)

    task_config = orchestrator.TaskConfig(
        experiment=orchestrator.ExperimentConfig(
            name="exp",
            max_agent_steps=5,
        ),
        operators=["activation/relu"],
    )
    launch_config = orchestrator.TreeCodeLaunchConfig(
        model="test-model",
        base_url="http://localhost:8000/v1",
        api_key="EMPTY",
        api_format="openai",
    )

    request, response = orchestrator.run_agent_round(
        task_config,
        launch_config,
        tmp_path,
        tmp_path / "round_0",
        "system prompt",
        "user prompt",
    )

    build_kwargs = captured["build_kwargs"]
    assert build_kwargs["cwd"] == tmp_path
    assert build_kwargs["model"] == "test-model"
    assert build_kwargs["base_url"] == "http://localhost:8000/v1"
    assert build_kwargs["api_key"] == "EMPTY"
    assert build_kwargs["api_format"] == "openai"
    assert "max_tokens" not in build_kwargs
    assert build_kwargs["max_turns"] == 5
    assert build_kwargs["permission_mode"] == "full_auto"
    assert "system prompt" in build_kwargs["extra_system_prompt_suffix"]
    assert captured["started"] is True
    assert captured["closed"] is True
    assert captured["line"] == "user prompt"
    assert request["workspace_root"] == str(tmp_path)
    assert request["model"] == "test-model"
    assert request["max_tokens"] == 1234
    assert request["provider"] == "openai-compatible"
    assert request["base_url"] == "http://localhost:8000/v1"
    assert request["api_format"] == "openai"
    assert response["assistant_content"] == "done"
    assert response["tool_called"] is True
    assert response["token_usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 11,
        "total_tokens": 18,
    }
    assert "TOOL CALL" in (tmp_path / "round_0" / "trajectory.log").read_text(encoding="utf-8")
