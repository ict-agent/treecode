"""Tool for waiting until a background task completes."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from openharness.tasks.manager import get_task_manager
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

_TERMINAL_STATUSES = {"completed", "failed", "killed"}


class TaskWaitToolInput(BaseModel):
    """Arguments for task_wait."""

    task_id: str = Field(description="Task identifier to wait for")
    timeout_seconds: float = Field(
        default=120.0,
        ge=1.0,
        le=600.0,
        description="Maximum seconds to wait before returning. Default 120s.",
    )
    poll_interval_seconds: float = Field(
        default=3.0,
        ge=0.5,
        le=30.0,
        description="How often to check task status. Default 3s.",
    )


class TaskWaitTool(BaseTool):
    """Wait for a background task to finish, polling at regular intervals.

    Returns as soon as the task reaches a terminal status (completed/failed/killed)
    or when the timeout is reached. More efficient than sleep + task_get polling.
    """

    name = "task_wait"
    description = (
        "Wait for a oneshot background task to finish, returning as soon as it completes "
        "(or fails). Polls every poll_interval_seconds up to timeout_seconds. "
        "ONLY use for oneshot agents (spawn_mode='oneshot') which exit after completing. "
        "Do NOT use for persistent agents (spawn_mode='persistent') — they stay running "
        "indefinitely and task_wait will always time out, blocking the main agent. "
        "For persistent agents, use sleep + task_output instead and look for [status] idle."
    )
    input_model = TaskWaitToolInput

    def is_read_only(self, arguments: TaskWaitToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: TaskWaitToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        manager = get_task_manager()
        elapsed = 0.0
        interval = arguments.poll_interval_seconds
        timeout = arguments.timeout_seconds

        while elapsed < timeout:
            try:
                task = manager.get_task(arguments.task_id)
            except Exception:
                task = None

            if task is None:
                return ToolResult(
                    output=f"Task {arguments.task_id} not found.",
                    is_error=True,
                )

            if task.status in _TERMINAL_STATUSES:
                return ToolResult(
                    output=(
                        f"Task {arguments.task_id} finished with status={task.status} "
                        f"after {elapsed:.1f}s. "
                        f"Use task_output(task_id='{arguments.task_id}') to read results."
                    )
                )

            wait = min(interval, timeout - elapsed)
            await asyncio.sleep(wait)
            elapsed += wait

        # Timed out
        try:
            task = manager.get_task(arguments.task_id)
            status = task.status if task else "unknown"
        except Exception:
            status = "unknown"

        return ToolResult(
            output=(
                f"Timed out after {timeout:.0f}s waiting for task {arguments.task_id} "
                f"(current status={status}). "
                f"You can call task_wait again or use task_output to read partial results."
            )
        )
