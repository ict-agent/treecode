"""Subprocess-based TeammateExecutor implementation."""

from __future__ import annotations

import json
import logging
import shlex
from typing import TYPE_CHECKING

from openharness.swarm.spawn_utils import (
    build_inherited_cli_flags,
    build_inherited_env_vars,
    get_teammate_command,
)
from openharness.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateMessage,
    TeammateSpawnConfig,
)
from openharness.tasks.manager import get_task_manager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_spawn_mode() -> str:
    """Read swarm.spawn_mode from settings. Returns 'print' or 'backend'."""
    try:
        from openharness.config.settings import load_settings
        return load_settings().swarm.spawn_mode
    except Exception:
        return "print"


class SubprocessBackend:
    """TeammateExecutor that runs each teammate as a separate subprocess.

    Supports two spawn modes (configured via settings.swarm.spawn_mode):
    - "print": runs ``openharness -p <prompt> --output-format stream-json``
      One-shot, clean output, no stdin needed. Default.
    - "backend": runs ``openharness --backend-only`` with prompt via stdin.
      Persistent, full OHJSON event stream, supports multi-turn via send_message.
    """

    type: BackendType = "subprocess"

    _agent_tasks: dict[str, str]

    def __init__(self) -> None:
        self._agent_tasks = {}

    def is_available(self) -> bool:
        return True

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        agent_id = f"{config.name}@{config.team}"
        spawn_mode = _get_spawn_mode()

        extra_env = build_inherited_env_vars()
        env_prefix = " ".join(f"{k}={v!r}" for k, v in extra_env.items())
        teammate_cmd = get_teammate_command()

        if spawn_mode == "print":
            command = self._build_print_command(
                teammate_cmd, config, env_prefix,
            )
        else:
            command = self._build_backend_command(
                teammate_cmd, config, env_prefix,
            )

        manager = get_task_manager()
        try:
            if spawn_mode == "print":
                record = await manager.create_shell_task(
                    command=command,
                    description=f"Teammate: {agent_id}",
                    cwd=config.cwd,
                    task_type="in_process_teammate",
                )
            else:
                record = await manager.create_agent_task(
                    prompt=config.prompt,
                    description=f"Teammate: {agent_id}",
                    cwd=config.cwd,
                    task_type="in_process_teammate",
                    model=config.model,
                    command=command,
                )
        except Exception as exc:
            logger.error("Failed to spawn teammate %s: %s", agent_id, exc)
            return SpawnResult(
                task_id="",
                agent_id=agent_id,
                backend_type=self.type,
                success=False,
                error=str(exc),
            )

        self._agent_tasks[agent_id] = record.id
        logger.debug("Spawned teammate %s as task %s (mode=%s)", agent_id, record.id, spawn_mode)
        return SpawnResult(
            task_id=record.id,
            agent_id=agent_id,
            backend_type=self.type,
        )

    def _build_print_command(
        self,
        teammate_cmd: str,
        config: TeammateSpawnConfig,
        env_prefix: str,
    ) -> str:
        """Build a one-shot -p command with stream-json output."""
        flags = [
            "-p", shlex.quote(config.prompt),
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]
        if config.model:
            flags.extend(["--model", shlex.quote(config.model)])

        cmd_parts = [teammate_cmd] + flags
        return f"{env_prefix} {' '.join(cmd_parts)}" if env_prefix else " ".join(cmd_parts)

    def _build_backend_command(
        self,
        teammate_cmd: str,
        config: TeammateSpawnConfig,
        env_prefix: str,
    ) -> str:
        """Build a persistent --backend-only command."""
        flags = build_inherited_cli_flags(
            model=config.model,
            plan_mode_required=config.plan_mode_required,
        )
        cmd_parts = [teammate_cmd] + flags
        return f"{env_prefix} {' '.join(cmd_parts)}" if env_prefix else " ".join(cmd_parts)

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """Send a message to a running teammate via its stdin pipe.

        Only works in "backend" spawn mode. In "print" mode the agent is
        one-shot and does not accept further input.
        """
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            raise ValueError(f"No active subprocess for agent {agent_id!r}")

        payload = {
            "text": message.text,
            "from": message.from_agent,
            "timestamp": message.timestamp,
        }
        if message.color:
            payload["color"] = message.color
        if message.summary:
            payload["summary"] = message.summary

        manager = get_task_manager()
        await manager.write_to_task(task_id, json.dumps(payload))
        logger.debug("Sent message to %s (task %s)", agent_id, task_id)

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool:
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            logger.warning("shutdown() called for unknown agent %s", agent_id)
            return False

        manager = get_task_manager()
        try:
            await manager.stop_task(task_id)
        except ValueError as exc:
            logger.debug("stop_task for %s: %s", task_id, exc)
        finally:
            self._agent_tasks.pop(agent_id, None)

        logger.debug("Shut down teammate %s (task %s)", agent_id, task_id)
        return True

    def get_task_id(self, agent_id: str) -> str | None:
        return self._agent_tasks.get(agent_id)
