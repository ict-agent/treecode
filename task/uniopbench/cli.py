"""UniOpBench task CLI. Parses its own args and delegates to the orchestrator."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_orchestrator():
    orchestrator_path = Path(__file__).resolve().parent / "orchestrator.py"
    spec = importlib.util.spec_from_file_location("uniopbench_orchestrator", orchestrator_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load orchestrator from {orchestrator_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by run and optimize subcommands."""
    parser.add_argument(
        "--config",
        help="Override task config path (default: task/uniopbench/task.yaml)",
    )
    parser.add_argument(
        "--run-id",
        help="Run id (defaults to a timestamp if not given)",
    )
    parser.add_argument(
        "--operators",
        help="Optional comma-separated operator override list",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Disable truncation in agent output (full system prompt, full tool results)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a prior run id",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UniOpBench experiment runner")
    parser.add_argument(
        "--task",
        choices=["uniopbench"],
        default="uniopbench",
        help="Task (always uniopbench when invoked from this module)",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # --- run (default) ---
    run_parser = subparsers.add_parser("run", help="Run correctness + perf evaluation")
    _add_common_args(run_parser)
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Create prompts and run layout without calling the LLM",
    )

    # --- optimize ---
    opt_parser = subparsers.add_parser("optimize", help="Optimize kernels (self-contained, no prior run needed)")
    _add_common_args(opt_parser)
    opt_parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="Max optimization rounds (pass@k context restarts) per operator (default: 3)",
    )
    opt_parser.add_argument(
        "--max-version",
        type=int,
        default=None,
        help="Max versioning rounds before give-up when target not met (default: same as --rounds)",
    )
    opt_parser.add_argument(
        "--target-speedup",
        type=float,
        default=1.0,
        help="Target speedup to achieve (default: 1.0x)",
    )
    opt_parser.add_argument(
        "--ref-impl",
        type=str,
        default=None,
        help="Path to a reference kernel.cu to use as v0 baseline (not counted as a round)",
    )
    opt_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Create prompts and run layout without calling the LLM",
    )

    return parser


_KNOWN_SUBCOMMANDS = {"run", "optimize"}


def _normalize_argv(argv: list[str]) -> list[str]:
    """Normalize argv for argparse: strip program name, ensure subcommand is first positional.

    Handles:
    - _run_uniopbench passes sys.argv (with program name as argv[0])
    - User may put subcommand anywhere: --operators x optimize --rounds 3
    - Missing subcommand defaults to 'run'
    """
    args = list(argv)
    # Strip program name if present (not a flag, not a subcommand)
    if args and not args[0].startswith("-") and args[0] not in _KNOWN_SUBCOMMANDS:
        args = args[1:]

    # Find and extract the subcommand, move it to front
    subcmd = None
    subcmd_idx = None
    # Track which positional args are actually values of preceding flags
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("-"):
            # Flags that consume next arg as value
            if "=" not in arg and arg in {
                "--config", "--run-id", "--operators", "--rounds",
                "--max-version", "--target-speedup", "--ref-impl", "--task",
            }:
                skip_next = True
            continue
        if arg in _KNOWN_SUBCOMMANDS:
            subcmd = arg
            subcmd_idx = i
            break

    if subcmd is not None and subcmd_idx is not None:
        args.pop(subcmd_idx)
        args.insert(0, subcmd)
    elif subcmd is None:
        args.insert(0, "run")

    return args


def run(argv: list[str] | None = None) -> int:
    raw_argv = argv if argv is not None else sys.argv[1:]
    normalized = _normalize_argv(raw_argv)

    parser = build_parser()
    args, _ = parser.parse_known_args(normalized)
    orchestrator = _load_orchestrator()

    if not hasattr(args, "dry_run"):
        args.dry_run = False
    if not hasattr(args, "resume"):
        args.resume = False

    if args.subcommand == "optimize":
        return orchestrator.run_optimize_task(args)

    # 'run' subcommand
    return orchestrator.run_uniopbench_task(args)
