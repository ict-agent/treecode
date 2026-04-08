"""Tool for spawning local agent tasks.

NOTE: This module defines the AgentTool class for the OpenHarness tool system.
It is NOT callable as a plain Python function. Use the `agent` tool via the
LLM tool-call interface (not via Python import/bash).
"""

from __future__ import annotations

import logging
import uuid

from pydantic import BaseModel, Field

from openharness.coordinator.agent_definitions import get_agent_definition
from openharness.coordinator.coordinator_mode import get_team_registry
from openharness.swarm.context_registry import AgentContextSnapshot, get_context_registry
from openharness.swarm.event_store import get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.registry import get_backend_registry
from openharness.swarm.types import TeammateSpawnConfig
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class AgentToolInput(BaseModel):
    """Arguments for local agent spawning."""

    description: str = Field(description="Short description of the delegated work")
    prompt: str = Field(description="Full prompt for the local agent")
    subagent_type: str | None = Field(
        default=None,
        description="Agent type for definition lookup (e.g. 'general-purpose', 'Explore', 'worker')",
    )
    model: str | None = Field(default=None)
    command: str | None = Field(default=None, description="Override spawn command")
    team: str | None = Field(default=None, description="Optional team to attach the agent to")
    mode: str = Field(
        default="local_agent",
        description="Agent mode: local_agent, remote_agent, or in_process_teammate",
    )
    spawn_mode: str = Field(
        default="oneshot",
        description=(
            "Sub-agent lifetime. "
            '"oneshot" (default): agent runs the prompt and exits — use for most tasks '
            "(file operations, search, code review, one-off analysis). "
            '"persistent": agent stays alive after completing so you can send follow-up '
            "messages via send_message — only for multi-turn workflows like "
            "ongoing monitoring, iterative editing, or long-running assistants."
        ),
    )


class AgentTool(BaseTool):
    """Spawn a local background agent subprocess.

    Use spawn_mode="oneshot" (default) for most tasks — the agent runs and exits.
    Use spawn_mode="persistent" only when you need multi-turn interaction via send_message.
    """

    name = "agent"
    description = (
        "Spawn a local background agent to handle a delegated task. "
        "Default spawn_mode='oneshot': agent runs the prompt and exits (use for most tasks). "
        "Use spawn_mode='persistent' only when you need to send follow-up messages."
    )
    input_model = AgentToolInput

    @staticmethod
    def _resolve_tree_metadata(context: ToolExecutionContext) -> tuple[str, str | None, str | None, list[str]]:
        """Resolve parent/root lineage from the current tool execution context."""
        metadata = context.metadata
        parent_session_id = str(metadata.get("session_id", "main"))
        parent_agent_id = metadata.get("swarm_agent_id")
        root_agent_id = metadata.get("swarm_root_agent_id")
        lineage_path = metadata.get("swarm_lineage_path") or []
        lineage = [str(item) for item in lineage_path]
        if parent_agent_id is not None:
            parent_agent_id = str(parent_agent_id)
        if root_agent_id is not None:
            root_agent_id = str(root_agent_id)
        elif lineage:
            root_agent_id = lineage[0]
        elif parent_agent_id is not None:
            root_agent_id = parent_agent_id
        return parent_session_id, parent_agent_id, root_agent_id, lineage

    @staticmethod
    def _allocate_unique_swarm_identity(base_name: str, team: str | None) -> tuple[str, str]:
        """Return (name, team) so ``name@team`` is not already in the context registry.

        Without this, nested ``agent`` tool calls often reuse the same default
        ``subagent_type`` (e.g. ``agent@default``) and overwrite the prior teammate.
        """
        registry = get_context_registry()
        base = (base_name or "agent").strip() or "agent"
        team_norm = (team or "default").strip() or "default"

        def full_id(name_part: str) -> str:
            return f"{name_part}@{team_norm}"

        if registry.get(full_id(base)) is None:
            return base, team_norm
        for i in range(1, 10_000):
            candidate = f"{base}-{i}"
            if registry.get(full_id(candidate)) is None:
                logger.info(
                    "Swarm id %s already registered; spawning as %s instead",
                    full_id(base),
                    full_id(candidate),
                )
                return candidate, team_norm
        suffix = uuid.uuid4().hex[:8]
        candidate = f"{base}-{suffix}"
        logger.warning(
            "Swarm id space exhausted for base %r; using %s",
            base,
            full_id(candidate),
        )
        return candidate, team_norm

    async def execute(self, arguments: AgentToolInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.mode not in {"local_agent", "remote_agent", "in_process_teammate"}:
            return ToolResult(
                output="Invalid mode. Use local_agent, remote_agent, or in_process_teammate.",
                is_error=True,
            )
        if arguments.spawn_mode not in {"oneshot", "persistent"}:
            return ToolResult(
                output='Invalid spawn_mode. Use "oneshot" (default) or "persistent".',
                is_error=True,
            )

        # Look up agent definition if subagent_type is specified
        agent_def = None
        if arguments.subagent_type:
            agent_def = get_agent_definition(arguments.subagent_type)

        # Resolve team and agent name for the swarm backend
        team = arguments.team or "default"
        agent_name = arguments.subagent_type or "agent"
        agent_name, team = self._allocate_unique_swarm_identity(agent_name, team)
        parent_session_id, parent_agent_id, root_agent_id, lineage_path = self._resolve_tree_metadata(
            context
        )

        registry = get_backend_registry()
        if arguments.mode == "in_process_teammate":
            try:
                executor = registry.get_executor("in_process")
            except KeyError:
                executor = registry.get_executor("subprocess")
        else:
            try:
                executor = registry.get_executor("subprocess")
            except KeyError:
                executor = registry.get_executor()

        config = TeammateSpawnConfig(
            name=agent_name,
            team=team,
            prompt=arguments.prompt,
            cwd=str(context.cwd),
            parent_session_id=parent_session_id,
            parent_agent_id=parent_agent_id,
            root_agent_id=root_agent_id,
            model=arguments.model or (agent_def.model if agent_def else None),
            system_prompt=agent_def.system_prompt if agent_def else None,
            permissions=agent_def.permissions if agent_def else [],
            spawn_mode=arguments.spawn_mode,
            lineage_path=lineage_path,
        )
        event_store = get_event_store()
        event_store.append(
            new_swarm_event(
                "agent_spawn_requested",
                agent_id=config.resolved_agent_id(),
                parent_agent_id=config.parent_agent_id,
                root_agent_id=config.resolved_root_agent_id(),
                session_id=config.session_id or config.resolved_agent_id(),
                payload={
                    "name": config.name,
                    "team": config.team,
                    "lineage_path": list(config.resolved_lineage_path()),
                    "spawn_mode": config.spawn_mode,
                },
            )
        )

        try:
            result = await executor.spawn(config)
        except Exception as exc:
            logger.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        get_context_registry().register(
            AgentContextSnapshot(
                agent_id=result.agent_id,
                session_id=config.session_id or result.agent_id,
                parent_agent_id=config.parent_agent_id,
                root_agent_id=config.resolved_root_agent_id(),
                lineage_path=config.resolved_lineage_path(),
                prompt=arguments.prompt,
                system_prompt=config.system_prompt,
                metadata={
                    "description": arguments.description,
                    "spawn_mode": config.spawn_mode,
                },
            )
        )

        event_store.append(
            new_swarm_event(
                "agent_spawned",
                agent_id=result.agent_id,
                parent_agent_id=config.parent_agent_id,
                root_agent_id=config.resolved_root_agent_id(),
                session_id=config.session_id or result.agent_id,
                payload={
                    "name": config.name,
                    "team": config.team,
                    "lineage_path": list(config.resolved_lineage_path()),
                    "spawn_mode": config.spawn_mode,
                    "backend_type": result.backend_type,
                    "task_id": result.task_id,
                },
            )
        )
        if config.parent_agent_id is not None:
            event_store.append(
                new_swarm_event(
                    "agent_attached_to_parent",
                    agent_id=result.agent_id,
                    parent_agent_id=config.parent_agent_id,
                    root_agent_id=config.resolved_root_agent_id(),
                    session_id=config.session_id or result.agent_id,
                    payload={
                        "parent_agent_id": config.parent_agent_id,
                        "lineage_path": list(config.resolved_lineage_path()),
                    },
                )
            )

        if arguments.team:
            team_registry = get_team_registry()
            try:
                team_registry.add_agent(arguments.team, result.task_id)
            except ValueError:
                team_registry.create_team(arguments.team, description="Auto-created by agent tool")
                team_registry.add_agent(arguments.team, result.task_id)

        task_id = result.task_id

        if arguments.spawn_mode == "oneshot":
            output = (
                f"Spawned oneshot agent {result.agent_id} (task_id={task_id})\n"
                f"Agent will exit after completing the prompt.\n"
                f"To check progress: call task_wait(task_id='{task_id}') — it returns "
                f"immediately with current status. If status=running, sleep a few seconds "
                f"and call task_wait again. Once status=completed, call "
                f"task_output(task_id='{task_id}') to read results."
            )
        else:
            output = (
                f"Spawned persistent agent {result.agent_id} (task_id={task_id})\n"
                f"Agent stays alive for multi-turn interaction.\n"
                f"- After spawning, sleep(seconds=10) then task_output(task_id='{task_id}') "
                f"to read the initial response (look for [status] idle).\n"
                f"- Use send_message(task_id='{task_id}', message='...') for follow-up tasks; "
                f"then sleep a few seconds and task_output again to see the response.\n"
                f"- task_wait always returns status=running for persistent agents (by design). "
                f"Use task_output + [status] idle to know when a message was processed.\n"
                f"- Use task_stop(task_id='{task_id}') when done."
            )

        return ToolResult(output=output)
