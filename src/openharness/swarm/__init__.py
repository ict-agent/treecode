"""Swarm backend abstraction for teammate execution."""

from openharness.swarm.mailbox import (
    MailboxMessage,
    TeammateMailbox,
    create_idle_notification,
    create_shutdown_request,
    create_user_message,
    get_agent_mailbox_dir,
    get_team_dir,
)
from openharness.swarm.context_registry import (
    AgentContextRegistry,
    AgentContextSnapshot,
    get_context_registry,
)
from openharness.swarm.debug_server import SwarmDebugServer
from openharness.swarm.debugger import SwarmDebuggerService, create_default_swarm_debugger_service
from openharness.swarm.event_store import EventStore, get_event_store
from openharness.swarm.events import SwarmEvent, new_swarm_event
from openharness.swarm.permission_sync import (
    SwarmPermissionRequest,
    SwarmPermissionResponse,
    create_permission_request,
    handle_permission_request,
    poll_permission_response,
    send_permission_request,
    send_permission_response,
)
from openharness.swarm.registry import BackendRegistry, get_backend_registry
from openharness.swarm.router import MessageRouter
from openharness.swarm.runtime_graph import AgentNode, RuntimeGraph
from openharness.swarm.projections import SwarmProjection
from openharness.swarm.subprocess_backend import SubprocessBackend
from openharness.swarm.types import (
    BackendType,
    SpawnResult,
    TeammateExecutor,
    TeammateIdentity,
    TeammateMessage,
    TeammateSpawnConfig,
)

__all__ = [
    "BackendRegistry",
    "BackendType",
    "AgentContextRegistry",
    "AgentContextSnapshot",
    "AgentNode",
    "EventStore",
    "MailboxMessage",
    "MessageRouter",
    "RuntimeGraph",
    "SpawnResult",
    "SwarmDebugServer",
    "SwarmDebuggerService",
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
