"""Tool for spawning local agent tasks.

NOTE: This module defines the AgentTool class for the OpenHarness tool system.
It is NOT callable as a plain Python function. Use the `agent` tool via the
LLM tool-call interface (not via Python import/bash).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from openharness.coordinator.agent_definitions import get_agent_definition
from openharness.coordinator.coordinator_mode import get_team_registry
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

        # Use subprocess backend (in_process lacks QueryContext wiring for now)
        registry = get_backend_registry()
        try:
            executor = registry.get_executor("subprocess")
        except KeyError:
            executor = registry.get_executor()

        config = TeammateSpawnConfig(
            name=agent_name,
            team=team,
            prompt=arguments.prompt,
            cwd=str(context.cwd),
            parent_session_id="main",
            model=arguments.model or (agent_def.model if agent_def else None),
            system_prompt=agent_def.system_prompt if agent_def else None,
            permissions=agent_def.permissions if agent_def else [],
            spawn_mode=arguments.spawn_mode,
        )

        try:
            result = await executor.spawn(config)
        except Exception as exc:
            logger.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        if arguments.team:
            get_team_registry().add_agent(arguments.team, result.task_id)

        task_id = result.task_id

        if arguments.spawn_mode == "oneshot":
            output = (
                f"Spawned oneshot agent {result.agent_id} (task_id={task_id})\n"
                f"Agent will exit after completing the prompt.\n"
                f"Use task_wait(task_id='{task_id}') to wait for completion, "
                f"then task_output(task_id='{task_id}') to read results."
            )
        else:
            output = (
                f"Spawned persistent agent {result.agent_id} (task_id={task_id})\n"
                f"Agent stays alive for multi-turn interaction.\n"
                f"IMPORTANT: Do NOT use task_wait — persistent agents never complete, "
                f"task_wait will always time out and block you.\n"
                f"- After spawning, use sleep(seconds=10) then task_output(task_id='{task_id}') "
                f"to read the initial response (look for [status] idle).\n"
                f"- Use send_message(task_id='{task_id}', message='...') for follow-up tasks; "
                f"then sleep a few seconds and call task_output again.\n"
                f"- Use task_stop(task_id='{task_id}') when done."
            )

        return ToolResult(output=output)
