"""Protocol models for the multi-agent web console WebSocket transport."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ConsoleClientMessageType = Literal["subscribe", "command"]
ConsoleServerMessageType = Literal["snapshot", "ack", "error", "archives", "compare_result", "repl_event"]


class ConsoleClientMessage(BaseModel):
    """A client-originated WebSocket message."""

    type: ConsoleClientMessageType
    command: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ConsoleServerMessage(BaseModel):
    """A server-originated WebSocket message."""

    type: ConsoleServerMessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
