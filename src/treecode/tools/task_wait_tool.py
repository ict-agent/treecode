"""Non-blocking task status check tool."""

from __future__ import annotations

from pydantic import BaseModel, Field

from treecode.tasks.manager import get_task_manager
from treecode.tools.base import BaseTool, ToolExecutionContext, ToolResult

_TERMINAL_STATUSES = {"completed", "failed", "killed"}


class TaskWaitToolInput(BaseModel):
    """Arguments for task_wait."""

    task_id: str = Field(description="Task identifier to check")


class TaskWaitTool(BaseTool):
    """Instantly return the current status of a background task.

    Non-blocking: returns immediately with the task's current status.
    The caller decides whether to keep polling (call task_wait again after a sleep)
    or proceed to read the output.

    Typical pattern for oneshot agents:
        1. task_wait(task_id) → if status=running, sleep(10) then call again
        2. Once status=completed, call task_output(task_id) to read results

    Also works for persistent agents:
        1. task_wait(task_id) → status=running (always, by design)
        2. Call task_output(task_id) and look for [status] idle to know if the
           current prompt was processed
    """

    name = "task_wait"
    description = (
        "Instantly check whether a background task (oneshot or persistent) has finished. "
        "Returns immediately with the current status — does NOT block. "
        "For oneshot agents: call task_wait, if status=running then sleep a few seconds "
        "and call task_wait again; once status=completed call task_output to read results. "
        "For persistent agents: status is always 'running'; use task_output and look for "
        "'[status] idle' to know when the current message was processed."
    )
    input_model = TaskWaitToolInput

    def is_read_only(self, arguments: TaskWaitToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: TaskWaitToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        manager = get_task_manager()

        try:
            task = manager.get_task(arguments.task_id)
        except Exception:
            task = None

        if task is None:
            return ToolResult(
                output=f"Task {arguments.task_id} not found.",
                is_error=True,
            )

        status = task.status
        task_id = arguments.task_id

        if status in _TERMINAL_STATUSES:
            return ToolResult(
                output=(
                    f"Task {task_id} has finished (status={status}). "
                    f"Call task_output(task_id='{task_id}') to read the results."
                )
            )

        # Still running
        if task.type in {"in_process_teammate", "local_agent", "remote_agent"}:
            return ToolResult(
                output=(
                    f"Task {task_id} is still running (status={status}). "
                    f"For a oneshot agent: sleep a few seconds then call task_wait again. "
                    f"For a persistent agent: call task_output(task_id='{task_id}') and "
                    f"check for '[status] idle' to see if the current message was processed."
                )
            )

        return ToolResult(
            output=f"Task {task_id} is still running (status={status})."
        )
