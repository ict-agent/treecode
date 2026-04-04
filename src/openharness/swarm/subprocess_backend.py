"""Subprocess-based TeammateExecutor implementation."""

from __future__ import annotations

import asyncio
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


class SubprocessBackend:
    """TeammateExecutor that runs each teammate as a separate subprocess.

    Spawn modes (set via TeammateSpawnConfig.spawn_mode):
    - "oneshot" (default): runs ``openharness -p <prompt> --output-format stream-json``.
      One-shot, exits after completing the prompt. Use for most tasks.
    - "persistent": runs ``openharness --backend-only``.
      Stays alive, accepts follow-up messages via send_message. Use for multi-turn workflows.
    """

    type: BackendType = "subprocess"

    _agent_tasks: dict[str, str]

    def __init__(self) -> None:
        self._agent_tasks = {}

    def is_available(self) -> bool:
        return True

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        agent_id = f"{config.name}@{config.team}"
        spawn_mode = config.spawn_mode  # "oneshot" or "persistent"

        extra_env = build_inherited_env_vars()
        env_prefix = " ".join(f"{k}={v!r}" for k, v in extra_env.items())
        teammate_cmd = get_teammate_command()

        manager = get_task_manager()
        try:
            if spawn_mode == "oneshot":
                command = self._build_oneshot_command(teammate_cmd, config, env_prefix)
                record = await manager.create_shell_task(
                    command=command,
                    description=f"Teammate: {agent_id}",
                    cwd=config.cwd,
                    task_type="in_process_teammate",
                )
            else:
                command = self._build_persistent_command(teammate_cmd, config, env_prefix)
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
        logger.debug(
            "Spawned teammate %s as task %s (spawn_mode=%s)", agent_id, record.id, spawn_mode
        )
        return SpawnResult(
            task_id=record.id,
            agent_id=agent_id,
            backend_type=self.type,
        )

    def _build_oneshot_command(
        self,
        teammate_cmd: str,
        config: TeammateSpawnConfig,
        env_prefix: str,
    ) -> str:
        """Build a -p one-shot command with stream-json output."""
        flags = [
            "-p", shlex.quote(config.prompt),
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]
        if config.model:
            flags.extend(["--model", shlex.quote(config.model)])
        cmd_parts = [teammate_cmd] + flags
        return f"{env_prefix} {' '.join(cmd_parts)}" if env_prefix else " ".join(cmd_parts)

    def _build_persistent_command(
        self,
        teammate_cmd: str,
        config: TeammateSpawnConfig,
        env_prefix: str,
    ) -> str:
        """Build a --backend-only persistent command."""
        flags = build_inherited_cli_flags(
            model=config.model,
            plan_mode_required=config.plan_mode_required,
        )
        cmd_parts = [teammate_cmd] + flags
        return f"{env_prefix} {' '.join(cmd_parts)}" if env_prefix else " ".join(cmd_parts)

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """Send a follow-up message to a persistent sub-agent via stdin.

        Uses the ReactBackendHost submit_line protocol.
        Only meaningful for persistent agents (spawn_mode="persistent").
        """
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            raise ValueError(f"No active subprocess for agent {agent_id!r}")

        payload = {"type": "submit_line", "line": message.text}
        manager = get_task_manager()
        await manager.write_to_task(task_id, json.dumps(payload))
        logger.debug("Sent message to %s (task %s)", agent_id, task_id)

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool:
        """Terminate a persistent sub-agent.

        For persistent agents: sends a graceful shutdown protocol message first,
        waits briefly, then uses SIGTERM/SIGKILL via the task manager.
        For oneshot agents that have already exited: cleans up the mapping.
        """
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            logger.warning("shutdown() called for unknown agent %s", agent_id)
            return False

        manager = get_task_manager()

        if not force:
            # Try graceful shutdown: send the backend-only protocol's shutdown message
            try:
                shutdown_msg = {"type": "shutdown"}
                await manager.write_to_task(task_id, json.dumps(shutdown_msg))
                await asyncio.sleep(2)
            except Exception:
                pass

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
