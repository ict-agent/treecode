"""Tool for writing messages to running agent tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from openharness.swarm.registry import get_backend_registry
from openharness.swarm.router import MessageRouter
from openharness.swarm.types import TeammateMessage
from openharness.tasks.manager import get_task_manager
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class SendMessageToolInput(BaseModel):
    """Arguments for sending a follow-up message to a task."""

    task_id: str = Field(description="Target local agent task id or swarm agent_id (name@team)")
    message: str = Field(description="Message to write to the task stdin")


class SendMessageTool(BaseTool):
    """Send a message to a running local agent task."""

    name = "send_message"
    description = (
        "Send a follow-up message to a running persistent sub-agent. "
        "After calling this, sleep(10) then task_output(task_id) to read the response. "
        "The response is ready when task_output ends with '[status] idle'. "
        "If not yet idle, sleep a few more seconds and call task_output again."
    )
    input_model = SendMessageToolInput

    @staticmethod
    def _resolve_sender_metadata(context: ToolExecutionContext) -> tuple[str, str | None, str, str | None]:
        """Resolve sender/lineage metadata for routed swarm messages."""
        sender_agent_id = str(context.metadata.get("swarm_agent_id", "coordinator"))
        parent_agent_id = context.metadata.get("swarm_parent_agent_id")
        if parent_agent_id is not None:
            parent_agent_id = str(parent_agent_id)
        root_agent_id = str(context.metadata.get("swarm_root_agent_id", sender_agent_id))
        session_id = context.metadata.get("session_id")
        if session_id is not None:
            session_id = str(session_id)
        return sender_agent_id, parent_agent_id, root_agent_id, session_id

    async def execute(self, arguments: SendMessageToolInput, context: ToolExecutionContext) -> ToolResult:
        # Swarm agents use agent_id format (name@team); plain task IDs go direct to task manager
        if "@" in arguments.task_id:
            return await self._send_swarm_message(arguments.task_id, arguments.message, context)
        # Plain task_id: persistent agents run --backend-only which expects the
        # ReactBackendHost JSON-lines protocol, not a raw string.
        import json as _json
        payload = _json.dumps({"type": "submit_line", "line": arguments.message})
        try:
            await get_task_manager().write_to_task(arguments.task_id, payload)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Sent message to task {arguments.task_id}")

    async def _send_swarm_message(
        self,
        agent_id: str,
        message: str,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Route a message to a swarm agent via the backend."""
        sender_agent_id, parent_agent_id, root_agent_id, session_id = self._resolve_sender_metadata(
            context
        )
        teammate_msg = TeammateMessage(text=message, from_agent=sender_agent_id)
        registry = get_backend_registry()

        def _executor():
            try:
                return registry.get_executor("in_process")
            except KeyError:
                try:
                    return registry.get_executor("subprocess")
                except KeyError:
                    return registry.get_executor()

        router = MessageRouter(_executor)
        try:
            await router.route_message(
                target_agent_id=agent_id,
                message=teammate_msg,
                parent_agent_id=parent_agent_id,
                root_agent_id=root_agent_id,
                session_id=session_id,
            )
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", agent_id, exc)
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Sent message to agent {agent_id}")
