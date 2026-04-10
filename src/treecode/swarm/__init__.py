"""Swarm backend abstraction for teammate execution."""

from __future__ import annotations

from importlib import import_module

from treecode.swarm.mailbox import (
    MailboxMessage,
    TeammateMailbox,
    create_idle_notification,
    create_shutdown_request,
    create_user_message,
    get_agent_mailbox_dir,
    get_team_dir,
)
from treecode.swarm.context_registry import (
    AgentContextRegistry,
    AgentContextSnapshot,
    get_context_registry,
)
from treecode.swarm.console_protocol import ConsoleClientMessage, ConsoleServerMessage
from treecode.swarm.event_store import EventStore, get_event_store
from treecode.swarm.events import SwarmEvent, new_swarm_event
from treecode.swarm.manager import AgentManager
from treecode.swarm.permission_sync import (
    SwarmPermissionRequest,
    SwarmPermissionResponse,
    create_permission_request,
    handle_permission_request,
    poll_permission_response,
    send_permission_request,
    send_permission_response,
)
from treecode.swarm.registry import BackendRegistry, get_backend_registry
from treecode.swarm.router import MessageRouter
from treecode.swarm.run_archive import RunArchiveRecord, RunArchiveStore
from treecode.swarm.runtime_graph import AgentNode, RuntimeGraph
from treecode.swarm.projections import SwarmProjection
from treecode.swarm.subprocess_backend import SubprocessBackend
from treecode.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateExecutor,
    TeammateIdentity,
    TeammateMessage,
    TeammateSpawnConfig,
)

# Deferred: importing debugger/console_ws/debug_server eagerly pulls in tools.agent_tool while
# tools/__init__.py is still loading (circular import). Load on first attribute access.
_LAZY_DEBUG_EXPORTS: dict[str, tuple[str, str]] = {
    "SwarmConsoleWsServer": ("treecode.swarm.console_ws", "SwarmConsoleWsServer"),
    "SwarmDebugServer": ("treecode.swarm.debug_server", "SwarmDebugServer"),
    "SwarmDebuggerService": ("treecode.swarm.debugger", "SwarmDebuggerService"),
    "create_default_swarm_debugger_service": ("treecode.swarm.debugger", "create_default_swarm_debugger_service"),
}

__all__ = [
    "BackendRegistry",
    "BackendType",
    "AgentContextRegistry",
    "AgentContextSnapshot",
    "AgentManager",
    "AgentNode",
    "ConsoleClientMessage",
    "ConsoleServerMessage",
    "EventStore",
    "MailboxMessage",
    "MessageRouter",
    "RunArchiveRecord",
    "RunArchiveStore",
    "RuntimeGraph",
    "SpawnResult",
    "SwarmDebugServer",
    "SwarmDebuggerService",
    "SwarmConsoleWsServer",
    "SwarmEvent",
    "SubprocessBackend",
    "SwarmProjection",
    "SwarmPermissionRequest",
    "SwarmPermissionResponse",
    "TeammateExecutor",
    "TeammateIdentity",
    "TeammateMailbox",
    "TeammateMessage",
    "TeammateSpawnConfig",
    "create_idle_notification",
    "create_default_swarm_debugger_service",
    "create_permission_request",
    "create_shutdown_request",
    "create_user_message",
    "get_context_registry",
    "get_event_store",
    "get_agent_mailbox_dir",
    "get_backend_registry",
    "get_team_dir",
    "handle_permission_request",
    "poll_permission_response",
    "send_permission_request",
    "send_permission_response",
    "new_swarm_event",
]


def __getattr__(name: str):
    """Lazy-load debugger/console modules to avoid circular imports with tools.agent_tool."""
    target = _LAZY_DEBUG_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
