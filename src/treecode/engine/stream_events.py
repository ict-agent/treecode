"""Events yielded by the query engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from treecode.api.usage import UsageSnapshot
from treecode.engine.messages import ConversationMessage


@dataclass(frozen=True)
class UserMessage:
    """User input message."""

    text: str


@dataclass(frozen=True)
class AssistantTextDelta:
    """Incremental assistant text."""

    text: str


@dataclass(frozen=True)
class AssistantTurnComplete:
    """Completed assistant turn."""

    message: ConversationMessage
    usage: UsageSnapshot


@dataclass(frozen=True)
class ToolExecutionStarted:
    """The engine is about to execute a tool."""

    tool_name: str
    tool_input: dict[str, Any]


@dataclass(frozen=True)
class ToolExecutionCompleted:
    """A tool has finished executing."""

    tool_name: str
    output: str
    is_error: bool = False


@dataclass(frozen=True)
class MaxTurnsReached:
    """The engine has reached the maximum turn limit."""

    max_turns: int


@dataclass(frozen=True)
class ErrorEvent:
    """An error that should be surfaced to the user."""

    message: str
    recoverable: bool = True


@dataclass(frozen=True)
class StatusEvent:
    """A transient system status message shown to the user."""

    message: str


StreamEvent = (
    UserMessage
    | AssistantTextDelta
    | AssistantTurnComplete
    | ToolExecutionStarted
    | ToolExecutionCompleted
    | MaxTurnsReached
    | ErrorEvent
    | StatusEvent
)
