"""Tool for creating background tasks."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from treecode.tasks.manager import get_task_manager
from treecode.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TaskCreateToolInput(BaseModel):
    """Arguments for task creation."""

    type: str = Field(default="local_bash", description="Task type: local_bash or local_agent")
    description: str = Field(description="Short task description")
    command: str | None = Field(default=None, description="Shell command for local_bash")
    prompt: str | None = Field(default=None, description="Prompt for local_agent")
    model: str | None = Field(default=None)


class TaskCreateTool(BaseTool):
    """Create a background task."""

    name = "task_create"
    description = (
        "Create a background shell or local-agent task. "
        "Use this for generic background work, not for swarm child agents. "
        "If you need a persistent subagent that appears in the swarm tree and accepts follow-up messages, "
        "use the agent tool with spawn_mode='persistent'."
    )
    input_model = TaskCreateToolInput

    async def execute(self, arguments: TaskCreateToolInput, context: ToolExecutionContext) -> ToolResult:
        manager = get_task_manager()
        if arguments.type == "local_bash":
            if not arguments.command:
                return ToolResult(output="command is required for local_bash tasks", is_error=True)
            task = await manager.create_shell_task(
                command=arguments.command,
                description=arguments.description,
                cwd=context.cwd,
            )
        elif arguments.type == "local_agent":
            if not arguments.prompt:
                return ToolResult(output="prompt is required for local_agent tasks", is_error=True)
            try:
                task = await manager.create_agent_task(
                    prompt=arguments.prompt,
                    description=arguments.description,
                    cwd=context.cwd,
                    model=arguments.model,
                    api_key=os.environ.get("ANTHROPIC_API_KEY"),
                )
            except ValueError as exc:
                return ToolResult(output=str(exc), is_error=True)
        else:
            return ToolResult(output=f"unsupported task type: {arguments.type}", is_error=True)

        if arguments.type == "local_agent":
            return ToolResult(
                output=(
                    f"Created task {task.id} ({task.type})\n"
                    "Note: this is a background local_agent task, not a swarm child.\n"
                    "If you want a persistent subagent in the swarm tree, use the agent tool with "
                    "spawn_mode='persistent'."
                )
            )
        return ToolResult(output=f"Created task {task.id} ({task.type})")
