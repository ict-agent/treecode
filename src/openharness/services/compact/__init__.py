"""Conversation compaction helpers."""

from __future__ import annotations

from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.services.token_estimation import estimate_tokens


def summarize_messages(
    messages: list[ConversationMessage],
    *,
    max_messages: int = 8,
) -> str:
    """Produce a compact textual summary of recent messages."""
    selected = messages[-max_messages:]
    lines: list[str] = []
    for message in selected:
        text = message.text.strip()
        if not text:
            continue
        lines.append(f"\n{message.role}: {text[:300]}")
    return "".join(lines)


def compact_messages(
    messages: list[ConversationMessage],
    *,
    preserve_recent: int = 6,
) -> list[ConversationMessage]:
    """Replace older conversation history with a synthetic summary message."""
    if len(messages) <= preserve_recent:
        return list(messages)

    older = messages[:-preserve_recent]
    newer = messages[-preserve_recent:]
    summary = summarize_messages(older)
    if not summary:
        return list(newer)
    return [
        ConversationMessage(
            role="assistant",
            content=[TextBlock(text=f"[conversation summary]\n{summary}")],
        ),
        *newer,
    ]


def estimate_conversation_tokens(messages: list[ConversationMessage]) -> int:
    """Estimate token usage for the current conversation transcript."""
    return sum(estimate_tokens(message.text) for message in messages)


__all__ = [
    "compact_messages",
    "estimate_conversation_tokens",
    "summarize_messages",
]
