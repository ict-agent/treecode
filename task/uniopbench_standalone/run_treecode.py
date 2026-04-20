#!/usr/bin/env python3
"""Standalone UniOpBench runner that drives TreeCode in non-interactive mode.

This script intentionally does not integrate with TreeCode's CLI framework.
It prepares an isolated workdir per UniOpBench operator, writes a platform
specific TASK.md, invokes ``treecode -p`` inside that workdir, then runs an
evaluation epilogue and stores the full trace/artifacts next to the generated
kernel.

Example:

    uv run python task/uniopbench_standalone/run_treecode.py \
      --benchmark-root /path/to/UniOpBench \
      --operators activation/relu \
      --model glm-5.1-fp8 \
      --api-format openai \
      --base-url http://localhost:8000/v1 \
      --api-key EMPTY
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK_ROOT = REPO_ROOT / "runs" / "uniopbench-treecode"


@dataclass
class CommandResult:
    name: str
    command: list[str]
    cwd: str
    log_path: str
    returncode: int


@dataclass
class OperatorSummary:
    operator: str
    workdir: str
    treecode: CommandResult | None
    evaluation: dict[str, CommandResult]
    status: str


def timestamp_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def default_benchmark_root() -> Path:
    env_root = os.environ.get("UNIOPBENCH_ROOT")
    if env_root:
        return Path(env_root)
    return REPO_ROOT / "benchmarks" / "UniOpBench"


def safe_operator_name(operator: str) -> str:
    return operator.replace("/", "__")


def split_operators(values: list[str] | None) -> list[str]:
    if not values:
        return ["all"]
    operators: list[str] = []
    for value in values:
        operators.extend(part.strip() for part in value.split(",") if part.strip())
    return operators or ["all"]


def list_all_operators(benchmark_root: Path) -> list[str]:
    operators_root = benchmark_root / "operators"
    return sorted(str(path.parent.relative_to(operators_root)) for path in operators_root.rglob("test.py"))


def resolve_operators(benchmark_root: Path, requested: list[str]) -> list[str]:
    resolved: list[str] = []
    for operator in requested:
        if operator.lower() == "all":
            resolved.extend(list_all_operators(benchmark_root))
        else:
            path = Path(operator)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Invalid operator path: {operator}")
            resolved.append(operator)

    deduped: list[str] = []
    seen: set[str] = set()
    for operator in resolved:
        if operator not in seen:
            deduped.append(operator)
            seen.add(operator)
    return deduped


def require_operator_dir(benchmark_root: Path, operator: str) -> Path:
    operator_dir = benchmark_root / "operators" / operator
    required = [
        operator_dir / "test.py",
        operator_dir / "cases.yaml",
        operator_dir / "torch_" / "ref.py",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Invalid UniOpBench operator {operator!r}; missing: {missing}")
    return operator_dir


def copy_operator_workdir(source_dir: Path, workdir: Path, *, overwrite: bool) -> None:
    if workdir.exists():
        if not overwrite:
            raise FileExistsError(f"Workdir already exists: {workdir}. Use --overwrite to replace it.")
        shutil.rmtree(workdir)
    shutil.copytree(
        source_dir,
        workdir,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            "*.so",
            "lib_cuda_kernel.so",
            ".DS_Store",
            "kernel.cu",
            "kernel.py",
        ),
    )
    (workdir / "cuda_").mkdir(parents=True, exist_ok=True)
    (workdir / "evaluation").mkdir(parents=True, exist_ok=True)
    (workdir / "trace").mkdir(parents=True, exist_ok=True)


def supports_variants(test_file: Path) -> bool:
    return "--variants" in test_file.read_text(encoding="utf-8", errors="replace")


def platform_task(platform: str, cuda_arch: str) -> str:
    if platform == "hygon-k100":
        return f"""# UniOpBench Hygon K100 Generation Task

You are working in an isolated UniOpBench operator workdir on a Hygon K100 DCU.

Target platform:
- ROCm/HIP-compatible kernel code
- Target architecture: {cuda_arch}
- The implementation file is `cuda_/kernel.cu`

Rules:
- Preserve the exported C interface expected by `test.py` and `check_cuda.py`.
- Use `torch_/ref.py` as the semantic reference.
- Do not edit benchmark tests, cases, or PyTorch reference code unless they are broken.
- Prefer simple, correct HIP/CUDA C++ first. Optimize only after correctness passes.
- Validate with `python test.py --compile-only`, then `python test.py --no-perf`, then `python test.py`.
- If variant mode is available, also run `python test.py --variants yaml --no-perf`.

When done, leave the final implementation in `cuda_/kernel.cu` and write a short
summary to `GENERATION_NOTES.md`.
"""

    return f"""# UniOpBench CUDA Generation Task

You are working in an isolated UniOpBench operator workdir.

Target platform:
- NVIDIA CUDA
- Target architecture: {cuda_arch}
- The implementation file is `cuda_/kernel.cu`

Rules:
- Preserve the exported C interface expected by `test.py` and `check_cuda.py`.
- Use `torch_/ref.py` as the semantic reference.
- Do not edit benchmark tests, cases, or PyTorch reference code unless they are broken.
- Prefer simple, correct CUDA C++ first. Optimize only after correctness passes.
- Validate with `python test.py --compile-only`, then `python test.py --no-perf`, then `python test.py`.
- If variant mode is available, also run `python test.py --variants yaml --no-perf`.

When done, leave the final implementation in `cuda_/kernel.cu` and write a short
summary to `GENERATION_NOTES.md`.
"""


def write_task_files(workdir: Path, *, operator: str, platform: str, cuda_arch: str, extra_prompt: str) -> str:
    task = platform_task(platform, cuda_arch)
    if extra_prompt:
        task = f"{task}\n\n## Extra Instructions\n\n{extra_prompt.strip()}\n"
    (workdir / "TASK.md").write_text(task, encoding="utf-8")

    prompt = f"""Read TASK.md and complete the UniOpBench kernel generation task.

Operator: {operator}

Inspect the local files in this workdir, especially:
- test.py
- cases.yaml
- torch_/ref.py
- check_cuda.py, if present

Create or replace cuda_/kernel.cu. Run the validation commands from TASK.md.
Stop once correctness passes and you have run the performance command once.
"""
    (workdir / "TREECODE_PROMPT.md").write_text(prompt, encoding="utf-8")
    return prompt


def build_env(args: argparse.Namespace, benchmark_root: Path, cuda_arch: str) -> dict[str, str]:
    env = os.environ.copy()
    python_path = env.get("PYTHONPATH", "")
    root_text = str(benchmark_root)
    if root_text not in python_path.split(os.pathsep):
        env["PYTHONPATH"] = root_text + (os.pathsep + python_path if python_path else "")

    env["UNIOPBENCH_TASK_CUDA_ARCH"] = cuda_arch
    env["UNIOPBENCH_TASK_COMPILE_BASELINE"] = "0"

    if args.max_tokens is not None:
        env["TREECODE_MAX_TOKENS"] = str(args.max_tokens)
    if args.max_turns is not None:
        env["TREECODE_MAX_TURNS"] = str(args.max_turns)
    if args.api_key:
        if (args.api_format or "").lower() == "openai":
            env["OPENAI_API_KEY"] = args.api_key
        else:
            env["ANTHROPIC_API_KEY"] = args.api_key
    return env


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for item in command:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        redacted.append(item)
        if item == "--api-key":
            redact_next = True
    return redacted


def tee_command(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    timeout: int | None = None,
) -> CommandResult:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"\n[{name}] cwd={cwd}")
    print(f"[{name}] $ {printable}")
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {printable}\n\n")
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                print(f"[{name}] {line}", end="")
                log.write(line)
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            returncode = proc.wait()
            message = f"\n[{name}] timed out after {timeout} seconds\n"
            print(message, end="")
            log.write(message)

    return CommandResult(
        name=name,
        command=redact_command(command),
        cwd=str(cwd),
        log_path=str(log_path),
        returncode=returncode,
    )


def build_treecode_command(args: argparse.Namespace, workdir: Path, prompt: str, trace_path: Path) -> list[str]:
    command = shlex.split(args.treecode_cmd)
    if args.model:
        command.extend(["--model", args.model])
    if args.api_format:
        command.extend(["--api-format", args.api_format])
    if args.base_url:
        command.extend(["--base-url", args.base_url])
    if args.max_turns is not None:
        command.extend(["--max-turns", str(args.max_turns)])
    for extra_arg in args.treecode_arg or []:
        command.extend(shlex.split(extra_arg))
    command.extend(
        [
            "--cwd",
            str(workdir),
            "--dangerously-skip-permissions",
            "--debug-output",
            str(trace_path),
            "-p",
            prompt,
        ]
    )
    return command


def evaluation_commands(*, variants: bool) -> list[tuple[str, list[str], bool]]:
    commands = [
        ("compile_only", [sys.executable, "test.py", "--compile-only"], True),
        ("verify", [sys.executable, "test.py", "--no-perf"], True),
        ("perf", [sys.executable, "test.py"], False),
    ]
    if variants:
        commands.append(("variants", [sys.executable, "test.py", "--variants", "yaml", "--no-perf"], True))
    return commands


def run_evaluation_epilogue(
    *,
    workdir: Path,
    env: dict[str, str],
    run_variants: bool,
    timeout: int | None,
) -> tuple[dict[str, CommandResult], str]:
    results: dict[str, CommandResult] = {}
    required_ok = True
    for name, command, required in evaluation_commands(variants=run_variants):
        result = tee_command(
            name=f"eval:{name}",
            command=command,
            cwd=workdir,
            env=env,
            log_path=workdir / "evaluation" / f"{name}.log",
            timeout=timeout,
        )
        results[name] = result
        if required and result.returncode != 0:
            required_ok = False

    kernel = workdir / "cuda_" / "kernel.cu"
    if kernel.is_file():
        shutil.copy2(kernel, workdir / "evaluation" / "final_kernel.cu")
    return results, "passed" if required_ok else "failed"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_operator_summary(path: Path, summary: OperatorSummary) -> None:
    write_json(
        path / "summary.json",
        {
            "operator": summary.operator,
            "workdir": summary.workdir,
            "treecode": asdict(summary.treecode) if summary.treecode else None,
            "evaluation": {name: asdict(result) for name, result in summary.evaluation.items()},
            "status": summary.status,
        },
    )
    lines = [
        f"# UniOpBench Result: {summary.operator}",
        "",
        f"- status: {summary.status}",
        f"- workdir: {summary.workdir}",
    ]
    if summary.treecode:
        lines.append(f"- treecode_returncode: {summary.treecode.returncode}")
    for name, result in summary.evaluation.items():
        lines.append(f"- {name}_returncode: {result.returncode}")
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_operator(args: argparse.Namespace, benchmark_root: Path, operator: str, run_root: Path) -> OperatorSummary:
    source_dir = require_operator_dir(benchmark_root, operator)
    operator_key = safe_operator_name(operator)
    workdir = run_root / "operators" / operator_key
    cuda_arch = args.cuda_arch or ("gfx928" if args.platform == "hygon-k100" else "sm_80")

    copy_operator_workdir(source_dir, workdir, overwrite=args.overwrite)
    prompt = write_task_files(
        workdir,
        operator=operator,
        platform=args.platform,
        cuda_arch=cuda_arch,
        extra_prompt=args.extra_prompt or "",
    )
    env = build_env(args, benchmark_root, cuda_arch)

    metadata = {
        "operator": operator,
        "source_dir": str(source_dir),
        "workdir": str(workdir),
        "platform": args.platform,
        "cuda_arch": cuda_arch,
        "benchmark_root": str(benchmark_root),
    }
    write_json(workdir / "run_metadata.json", metadata)

    treecode_result: CommandResult | None = None
    status = "dry_run"
    if not args.dry_run:
        trace_path = workdir / "trace" / "treecode_debug.log"
        command = build_treecode_command(args, workdir, prompt, trace_path)
        treecode_result = tee_command(
            name=f"treecode:{operator_key}",
            command=command,
            cwd=workdir,
            env=env,
            log_path=workdir / "trace" / "treecode_stdout.log",
            timeout=args.treecode_timeout,
        )
        status = "treecode_failed" if treecode_result.returncode != 0 else "generated"

    evaluation: dict[str, CommandResult] = {}
    if not args.dry_run and not args.no_eval:
        evaluation, eval_status = run_evaluation_epilogue(
            workdir=workdir,
            env=env,
            run_variants=args.eval_variants and supports_variants(source_dir / "test.py"),
            timeout=args.eval_timeout,
        )
        if treecode_result and treecode_result.returncode != 0:
            status = "treecode_failed"
        else:
            status = eval_status

    summary = OperatorSummary(
        operator=operator,
        workdir=str(workdir),
        treecode=treecode_result,
        evaluation=evaluation,
        status=status,
    )
    write_operator_summary(workdir, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone UniOpBench runner for TreeCode")
    parser.add_argument("--benchmark-root", type=Path, default=default_benchmark_root())
    parser.add_argument("--operators", action="append", help="Operator list; repeat or comma-separate. Default: all")
    parser.add_argument("--platform", choices=["cuda", "hygon-k100"], default="cuda")
    parser.add_argument("--cuda-arch", help="Target arch, e.g. sm_80 or gfx928")
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--run-id", default=timestamp_run_id())
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing operator workdir")
    parser.add_argument("--keep-going", action="store_true", help="Continue after a failed operator")
    parser.add_argument("--dry-run", action="store_true", help="Prepare workdirs/prompts without invoking TreeCode")
    parser.add_argument("--no-eval", action="store_true", help="Skip the evaluation epilogue")
    parser.add_argument("--eval-variants", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--eval-timeout", type=int, default=None)
    parser.add_argument("--treecode-timeout", type=int, default=None)
    parser.add_argument("--treecode-cmd", default=os.environ.get("TREECODE_CMD", "treecode"))
    parser.add_argument("--treecode-arg", action="append", help="Extra raw argument(s) forwarded to treecode")
    parser.add_argument("--model", help="Forwarded to treecode --model")
    parser.add_argument("--api-format", help="Forwarded to treecode --api-format")
    parser.add_argument("--base-url", help="Forwarded to treecode --base-url")
    parser.add_argument("--api-key", help="Placed in OPENAI_API_KEY or ANTHROPIC_API_KEY, not logged")
    parser.add_argument("--max-tokens", type=int, help="Sets TREECODE_MAX_TOKENS for TreeCode")
    parser.add_argument("--max-turns", type=int, help="Forwarded to treecode --max-turns and TREECODE_MAX_TURNS")
    parser.add_argument("--extra-prompt", help="Additional text appended to the generated TASK.md")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    benchmark_root = args.benchmark_root.resolve()
    if not benchmark_root.is_dir():
        raise FileNotFoundError(
            f"UniOpBench root not found: {benchmark_root}. "
            "Pass --benchmark-root or set UNIOPBENCH_ROOT."
        )
    if not (benchmark_root / "operators").is_dir():
        raise FileNotFoundError(f"UniOpBench operators directory not found under: {benchmark_root}")

    operators = resolve_operators(benchmark_root, split_operators(args.operators))
    run_root = args.work_root.resolve() / args.run_id
    run_root.mkdir(parents=True, exist_ok=True)

    summaries: list[OperatorSummary] = []
    exit_code = 0
    for operator in operators:
        print(f"\n=== UniOpBench operator: {operator} ===")
        try:
            summary = run_operator(args, benchmark_root, operator, run_root)
            summaries.append(summary)
            if summary.status not in {"passed", "dry_run", "generated"}:
                exit_code = 1
                if not args.keep_going:
                    break
        except Exception as exc:
            exit_code = 1
            print(f"[error] {operator}: {exc}", file=sys.stderr)
            if not args.keep_going:
                break

    write_json(
        run_root / "run_summary.json",
        {
            "run_id": args.run_id,
            "benchmark_root": str(benchmark_root),
            "operators": [summary.operator for summary in summaries],
            "results": {
                safe_operator_name(summary.operator): {
                    "status": summary.status,
                    "workdir": summary.workdir,
                }
                for summary in summaries
            },
        },
    )
    print(f"\nRun artifacts: {run_root}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
