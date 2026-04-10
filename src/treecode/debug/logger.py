"""Debug logger that records StreamEvents to a file.

This implements the StreamRenderer protocol, allowing it to be composed with
other renderers (TUI, print mode, etc.) without modifying core logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from treecode.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    MaxTurnsReached,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
    UserMessage,
)


class DebugLogger:
    """Records StreamEvents to a file in human-readable format.
    
    Can be composed with other renderers via the StreamRenderer protocol.
    
    Example:
        >>> logger = DebugLogger("debug.log")
        >>> # later, compose with existing renderer:
        >>> async def composite_renderer(event: StreamEvent):
        ...     await tui_renderer(event)
        ...     await logger(event)
    """
    
    def __init__(self, output_path: str | Path, *, append: bool = False):
        """Initialize debug logger.
        
        Args:
            output_path: File path for debug output. Created if doesn't exist.
            append: If True, append to existing file. If False (default), overwrite.
        """
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Track buffer for assistant messages
        self._assistant_buffer: str = ""
        # Track pending tool calls for parallel correspondence
        self._tool_call_index: int = 0
        self._pending_tools: list[str] = []  # tool names in order
        
        mode = "a" if append else "w"
        self._file = open(self.output_path, mode, encoding="utf-8", buffering=1)
    
    async def __call__(self, event: StreamEvent) -> None:
        """Handle a StreamEvent (implements StreamRenderer protocol)."""
        if isinstance(event, ToolExecutionStarted):
            await self._on_tool_started(event.tool_name, event.tool_input)
        elif isinstance(event, ToolExecutionCompleted):
            await self._on_tool_completed(event.tool_name, event.output, event.is_error)
        elif isinstance(event, AssistantTextDelta):
            await self._on_text_delta(event.text)
        elif isinstance(event, AssistantTurnComplete):
            usage = event.usage.model_dump() if event.usage else None
            text = event.message.text if event.message is not None else ""
            await self._on_assistant_complete(text, usage=usage)
        elif isinstance(event, MaxTurnsReached):
            await self._on_max_turns(event.max_turns)
        elif isinstance(event, UserMessage):
            await self._on_user_message(event.text)

    async def handle_dict(self, obj: dict[str, Any]) -> None:
        """Handle a dictionary-style event (e.g. from BackendEvent JSON)."""
        t = obj.get("type")
        if t == "assistant_delta":
            await self._on_text_delta(obj.get("text") or obj.get("message") or "")
        elif t == "assistant_complete":
            await self._on_assistant_complete(obj.get("message") or "", usage=obj.get("usage"))
        elif t == "tool_started":
            await self._on_tool_started(obj.get("tool_name", "unknown"), obj.get("tool_input", {}))
        elif t == "tool_completed":
            await self._on_tool_completed(obj.get("tool_name", "unknown"), obj.get("output", ""), obj.get("is_error", False))
        elif t == "transcript_item":
            item = obj.get("item") or {}
            if item.get("role") == "user":
                await self._on_user_message(item.get("text") or "")
        elif t == "max_turns_reached":
            await self._on_max_turns(obj.get("max_turns", 0))

    def handle_dict_sync(self, obj: dict[str, Any]) -> None:
        """Synchronous version of handle_dict for use in non-async contexts."""
        t = obj.get("type")
        if t == "assistant_delta":
            self._log_text_delta(obj.get("text") or obj.get("message") or "")
        elif t == "assistant_complete":
            self._log_assistant_complete(obj.get("message") or "", usage=obj.get("usage"))
        elif t == "tool_started":
            self._log_tool_started(obj.get("tool_name", "unknown"), obj.get("tool_input", {}))
        elif t == "tool_completed":
            self._log_tool_completed(obj.get("tool_name", "unknown"), obj.get("output", ""), obj.get("is_error", False))
        elif t == "transcript_item":
            item = obj.get("item") or {}
            if item.get("role") == "user":
                self._log_user_message(item.get("text") or "")
        elif t == "max_turns_reached":
            self._log_max_turns(obj.get("max_turns", 0))

    async def _on_tool_started(self, tool_name: str, tool_input: Any) -> None:
        self._log_tool_started(tool_name, tool_input)

    async def _on_tool_completed(self, tool_name: str, output: str, is_error: bool = False) -> None:
        self._log_tool_completed(tool_name, output, is_error)

    async def _on_text_delta(self, text: str) -> None:
        self._log_text_delta(text)

    async def _on_assistant_complete(self, message: str, usage: dict[str, Any] | None = None) -> None:
        self._log_assistant_complete(message, usage)

    async def _on_max_turns(self, max_turns: int) -> None:
        self._log_max_turns(max_turns)

    async def _on_user_message(self, text: str) -> None:
        self._log_user_message(text)

    def _log_tool_started(self, tool_name: str, tool_input: Any) -> None:
        """Record tool call start (Sync)."""
        # Flush any accumulated assistant text before the tool call
        if self._assistant_buffer:
            msg = self._assistant_buffer.strip()
            if msg:
                self._file.write(f"\n[ASSISTANT]\n{msg}\n")
            self._assistant_buffer = ""

        self._tool_call_index += 1
        idx = self._tool_call_index
        self._pending_tools.append(tool_name)

        self._file.write(f"\n[TOOL CALL #{idx}: {tool_name}]\n")
        
        # Format input nicely
        if isinstance(tool_input, dict):
            self._file.write(json.dumps(tool_input, ensure_ascii=False, indent=2))
        else:
            self._file.write(str(tool_input))
        self._file.write("\n")
        self._file.flush()
    
    def _log_tool_completed(self, tool_name: str, output: str, is_error: bool = False) -> None:
        """Record tool call completion (Sync)."""
        output = output.strip() if output else "(Empty)"
        
        # Match response to the corresponding call index
        if self._pending_tools:
            # Find and remove the first matching tool name
            try:
                pos = self._pending_tools.index(tool_name)
                self._pending_tools.pop(pos)
                idx = pos + (self._tool_call_index - len(self._pending_tools) - pos)
            except ValueError:
                idx = self._tool_call_index
            # Reset counter when all pending tools are done
            if not self._pending_tools:
                self._tool_call_index = 0
        else:
            idx = self._tool_call_index
        
        if is_error:
            self._file.write(f"\n[TOOL ERROR #{idx}: {tool_name}]\n{output}\n")
        else:
            self._file.write(f"\n[TOOL RESPONSE #{idx}: {tool_name}]\n{output}\n")
        self._file.flush()
    
    def _log_text_delta(self, text: str) -> None:
        """Accumulate assistant text (Sync)."""
        self._assistant_buffer += text
    
    def _log_assistant_complete(self, message: str, usage: dict[str, Any] | None = None) -> None:
        """Record complete assistant message (Sync)."""
        if self._assistant_buffer:
            msg = self._assistant_buffer.strip()
            if msg:
                self._file.write(f"\n[ASSISTANT]\n{msg}\n")
            self._assistant_buffer = ""
        elif message:
            # If no buffer (e.g. from handle_dict which might only have assistant_complete), use the message
            self._file.write(f"\n[ASSISTANT]\n{message.strip()}\n")
        
        # Optionally include usage info
        if usage:
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            total_tokens = input_tokens + output_tokens
            self._file.write(f"   ({input_tokens} in, {output_tokens} out, {total_tokens} total)\n")
        
        self._file.flush()
    
    def _log_max_turns(self, max_turns: int) -> None:
        """Record max turns reached (Sync)."""
        self._file.write(f"\n[INFO] Max turns reached ({max_turns})\n")
        self._file.flush()

    def _log_user_message(self, text: str) -> None:
        """Record user input (Sync)."""
        self._file.write(f"\n[USER]\n{text}\n")
        self._file.flush()

    async def close(self) -> None:
        """Close the output file."""
        if not self._file.closed:
            self._file.close()
