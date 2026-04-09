"""Subprocess-based TeammateExecutor implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from typing import TYPE_CHECKING

from openharness.swarm.spawn_utils import (
    build_inherited_cli_flags,
    build_inherited_env_vars,
    get_teammate_command,
)
from openharness.swarm.event_store import get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateMessage,
    TeammateSpawnConfig,
)
from openharness.tasks.manager import get_task_manager, load_persisted_task_record

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

    def _build_swarm_metadata(self, config: TeammateSpawnConfig) -> dict[str, str]:
        """Encode tree-aware swarm identity for subprocess teammates."""
        leader = config.leader_session_id or os.environ.get("OPENHARNESS_SWARM_LEADER_SESSION_ID") or ""
        meta = {
            "OPENHARNESS_SWARM_AGENT_ID": f"{config.name}@{config.team}",
            "OPENHARNESS_SWARM_PARENT_AGENT_ID": config.parent_agent_id or "",
            "OPENHARNESS_SWARM_ROOT_AGENT_ID": config.resolved_root_agent_id(),
            "OPENHARNESS_SWARM_PARENT_SESSION_ID": config.parent_session_id,
            "OPENHARNESS_SWARM_SESSION_ID": config.session_id or f"{config.name}@{config.team}",
            "OPENHARNESS_SWARM_LINEAGE_PATH": "::".join(config.resolved_lineage_path()),
        }
        if leader:
            meta["OPENHARNESS_SWARM_LEADER_SESSION_ID"] = leader
        return meta

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        agent_id = f"{config.name}@{config.team}"
        spawn_mode = config.spawn_mode  # "oneshot" or "persistent"

        extra_env = build_inherited_env_vars(self._build_swarm_metadata(config))
        env_prefix = " ".join(f"{k}={v!r}" for k, v in extra_env.items())
        teammate_cmd = get_teammate_command()

        manager = get_task_manager()
        try:
            if spawn_mode == "oneshot":
                if config.command:
                    command = (
                        f"{env_prefix} {config.command}" if env_prefix else config.command
                    )
                    record = await manager.create_agent_task(
                        prompt=config.prompt,
                        description=f"Teammate: {agent_id}",
                        cwd=config.cwd,
                        task_type="in_process_teammate",
                        model=config.model,
                        command=command,
                    )
                else:
                    command = self._build_oneshot_command(teammate_cmd, config, env_prefix)
                    record = await manager.create_shell_task(
                        command=command,
                        description=f"Teammate: {agent_id}",
                        cwd=config.cwd,
                        task_type="in_process_teammate",
                    )
            else:
                if config.command:
                    command = (
                        f"{env_prefix} {config.command}" if env_prefix else config.command
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
        get_event_store().append(
            new_swarm_event(
                "agent_became_running",
                agent_id=agent_id,
                parent_agent_id=config.parent_agent_id,
                root_agent_id=config.resolved_root_agent_id(),
                session_id=config.session_id or agent_id,
                payload={"status": "running", "task_id": record.id},
            )
        )
        logger.debug(
            "Spawned teammate %s as task %s (spawn_mode=%s)", agent_id, record.id, spawn_mode
        )

        # Background watcher: write idle_notification to leader mailbox when done
        asyncio.create_task(
            self._notify_leader_on_completion(
                record.id,
                agent_id,
                config.team,
                config.parent_agent_id,
                config.resolved_root_agent_id(),
                config.session_id or agent_id,
            ),
            name=f"notify-{record.id}",
        )

        return SpawnResult(
            task_id=record.id,
            agent_id=agent_id,
            backend_type=self.type,
        )

    async def _notify_leader_on_completion(
        self,
        task_id: str,
        agent_id: str,
        team: str,
        parent_agent_id: str | None,
        root_agent_id: str,
        session_id: str,
    ) -> None:
        """Poll until the task finishes, then write an idle_notification to the leader mailbox."""
        from openharness.swarm.mailbox import TeammateMailbox, create_idle_notification

        manager = get_task_manager()
        while True:
            await asyncio.sleep(2)
            task = manager.get_task(task_id)
            if task is None:
                break
            if task.status in {"completed", "failed", "killed"}:
                try:
                    msg = create_idle_notification(
                        sender=agent_id,
                        recipient="leader",
                        summary=(
                            f"{agent_id} finished with status={task.status}"
                        ),
                    )
                    leader_mailbox = TeammateMailbox(team_name=team, agent_id="leader")
                    await leader_mailbox.write(msg)
                    get_event_store().append(
                        new_swarm_event(
                            "agent_finished",
                            agent_id=agent_id,
                            parent_agent_id=parent_agent_id,
                            root_agent_id=root_agent_id,
                            session_id=session_id,
                            payload={"status": task.status, "task_id": task_id},
                        )
                    )
                    logger.debug(
                        "Wrote idle_notification for %s to leader mailbox (team=%s)",
                        agent_id, team,
                    )
                except Exception as exc:
                    logger.warning("Failed to write idle_notification for %s: %s", agent_id, exc)
                break

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
        task_id = self._agent_tasks.get(agent_id) or self._restore_task_mapping(agent_id)
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

    def restore_task_mapping(self, agent_id: str, task_id: str) -> None:
        """Register an existing persistent task mapping after process restart."""
        self._agent_tasks[agent_id] = task_id

    def _restore_task_mapping(self, agent_id: str) -> str | None:
        manager = get_task_manager()
        get_task = getattr(manager, "get_task", None)
        for event in reversed(get_event_store().all_events()):
            if event.event_type != "agent_spawned" or event.agent_id != agent_id:
                continue
            task_id = event.payload.get("task_id")
            if task_id is None:
                return None
            task_id = str(task_id)
            task = (get_task(task_id) if callable(get_task) else None) or load_persisted_task_record(task_id)
            if task is None or task.status in {"completed", "failed", "killed"}:
                return None
            self._agent_tasks[agent_id] = task_id
            return task_id
        return None
