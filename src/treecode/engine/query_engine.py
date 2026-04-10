"""High-level conversation engine."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from treecode.api.client import SupportsStreamingMessages
from treecode.engine.cost_tracker import CostTracker
from treecode.engine.messages import ConversationMessage
from treecode.engine.query import AskUserPrompt, PermissionPrompt, QueryContext, run_query
from treecode.engine.stream_events import StreamEvent
from treecode.hooks import HookExecutor
from treecode.permissions.checker import PermissionChecker
from treecode.tools.base import ToolRegistry


class QueryEngine:
    """Owns conversation history and the tool-aware model loop."""

    def __init__(
        self,
        *,
        api_client: SupportsStreamingMessages,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        max_tokens: int = 4096,
        max_turns: int = 20,
        permission_prompt: PermissionPrompt | None = None,
        ask_user_prompt: AskUserPrompt | None = None,
        hook_executor: HookExecutor | None = None,
        tool_metadata: dict[str, object] | None = None,
    ) -> None:
        self._api_client = api_client
        self._tool_registry = tool_registry
        self._permission_checker = permission_checker
        self._cwd = Path(cwd).resolve()
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._max_turns = max_turns
        self._permission_prompt = permission_prompt
        self._ask_user_prompt = ask_user_prompt
        self._hook_executor = hook_executor
        self._tool_metadata = tool_metadata or {}
        self._messages: list[ConversationMessage] = []
        self._cost_tracker = CostTracker()

    @property
    def messages(self) -> list[ConversationMessage]:
        """Return the current conversation history."""
        return list(self._messages)

    @property
    def total_usage(self):
        """Return the total usage across all turns."""
        return self._cost_tracker.total

    def clear(self) -> None:
        """Clear the in-memory conversation history."""
        self._messages.clear()
        self._cost_tracker = CostTracker()

    def set_system_prompt(self, prompt: str) -> None:
        """Update the active system prompt for future turns."""
        self._system_prompt = prompt

    def set_model(self, model: str) -> None:
        """Update the active model for future turns."""
        self._model = model

    def set_permission_checker(self, checker: PermissionChecker) -> None:
        """Update the active permission checker for future turns."""
        self._permission_checker = checker

    def set_max_turns(self, max_turns: int) -> None:
        """Dynamiclly set the maximum turn limit for future queries."""
        self._max_turns = max_turns

    def load_messages(self, messages: list[ConversationMessage]) -> None:
        """Replace the in-memory conversation history."""
        self._messages = list(messages)

    def to_query_context(self) -> QueryContext:
        """Snapshot engine settings as a :class:`QueryContext` for :func:`~treecode.engine.query.run_query`."""
        return QueryContext(
            api_client=self._api_client,
            tool_registry=self._tool_registry,
            permission_checker=self._permission_checker,
            cwd=self._cwd,
            model=self._model,
            system_prompt=self._system_prompt,
            max_tokens=self._max_tokens,
            max_turns=self._max_turns,
            permission_prompt=self._permission_prompt,
            ask_user_prompt=self._ask_user_prompt,
            hook_executor=self._hook_executor,
            tool_metadata=self._tool_metadata,
        )

    def append_slash_command_for_model_context(
        self,
        *,
        command_line: str,
        output_text: str | None,
        max_output_chars: int = 6000,
    ) -> None:
        """Append a user-role note so the next model turn sees a completed slash command.

        Used when the user ends a registered slash line with `` !!`` (see runtime).
        Does not run the query loop.
        """
        out = (output_text or "").strip()
        if len(out) > max_output_chars:
            out = out[:max_output_chars] + "\n…(truncated)"
        body = (
            "[Slash command recorded for model context]\n"
            f"{command_line.rstrip()}\n---\n{out if out else '(no text output)'}"
        )
        self._messages.append(ConversationMessage.from_user_text(body))

    async def submit_message(self, prompt: str) -> AsyncIterator[StreamEvent]:
        """Append a user message and execute the query loop."""
        self._messages.append(ConversationMessage.from_user_text(prompt))
        context = self.to_query_context()
        async for event, usage in run_query(context, self._messages):
            if usage is not None:
                self._cost_tracker.add(usage)
            yield event
