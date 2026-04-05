"""Debugger service for tree snapshots, playback, and control actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from openharness.swarm.context_registry import AgentContextRegistry, get_context_registry
from openharness.swarm.event_store import EventStore, get_event_store
from openharness.swarm.events import SwarmEvent, new_swarm_event
from openharness.swarm.manager import AgentManager
from openharness.swarm.permission_sync import (
    PermissionResolution,
    SwarmPermissionResponse,
    send_permission_response,
    send_permission_response_via_mailbox,
)
from openharness.swarm.projections import SwarmProjection
from openharness.swarm.registry import get_backend_registry
from openharness.swarm.router import MessageRouter
from openharness.swarm.types import TeammateMessage
from openharness.tasks import get_task_manager
from openharness.tasks.manager import load_persisted_task_record


class SwarmDebuggerService:
    """Aggregate runtime views and expose control operations for the web debugger."""

    def __init__(
        self,
        *,
        event_store: EventStore | None = None,
        context_registry: AgentContextRegistry | None = None,
        send_message: Callable[[str, str], Awaitable[dict[str, Any]]] | None = None,
        pause_agent: Callable[[str], Awaitable[bool]] | None = None,
        resume_agent: Callable[[str], Awaitable[bool]] | None = None,
        stop_agent: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._event_store = event_store or get_event_store()
        self._context_registry = context_registry or get_context_registry()
        self._send_message = send_message
        self._pause_agent = pause_agent
        self._resume_agent = resume_agent
        self._stop_agent = stop_agent

    def snapshot(self) -> dict[str, Any]:
        """Return the current debugger snapshot."""
        projection = self._build_projection(self._event_store.all_events())
        return self._projection_payload(projection)

    def playback(self, *, event_limit: int | None = None) -> dict[str, Any]:
        """Return a replay snapshot reconstructed from the event log prefix."""
        events = self._event_store.all_events()
        if event_limit is not None:
            events = events[:event_limit]
        projection = self._build_projection(events)
        return self._projection_payload(projection)

    async def send_message(self, agent_id: str, message: str) -> dict[str, Any]:
        """Send a debugger-originated message into the runtime."""
        if self._send_message is None:
            raise RuntimeError("Debugger send_message control is not configured")
        result = await self._send_message(agent_id, message)
        self._event_store.append(
            new_swarm_event(
                "manual_message_injected",
                agent_id=agent_id,
                root_agent_id=self._root_agent_id(agent_id),
                parent_agent_id=self._parent_agent_id(agent_id),
                session_id=self._session_id(agent_id),
                payload={"message": message, "source": "debugger"},
            )
        )
        return result

    async def pause_agent(self, agent_id: str) -> bool:
        """Pause an agent and record the event."""
        if self._pause_agent is None:
            raise RuntimeError("Debugger pause control is not configured")
        result = await self._pause_agent(agent_id)
        if result:
            self._event_store.append(
                new_swarm_event(
                    "agent_paused",
                    agent_id=agent_id,
                    root_agent_id=self._root_agent_id(agent_id),
                    parent_agent_id=self._parent_agent_id(agent_id),
                    session_id=self._session_id(agent_id),
                )
            )
        return result

    async def resume_agent(self, agent_id: str) -> bool:
        """Resume an agent and record the event."""
        if self._resume_agent is None:
            raise RuntimeError("Debugger resume control is not configured")
        result = await self._resume_agent(agent_id)
        if result:
            self._event_store.append(
                new_swarm_event(
                    "agent_resumed",
                    agent_id=agent_id,
                    root_agent_id=self._root_agent_id(agent_id),
                    parent_agent_id=self._parent_agent_id(agent_id),
                    session_id=self._session_id(agent_id),
                )
            )
        return result

    async def stop_agent(self, agent_id: str) -> bool:
        """Stop an agent and record the event."""
        if self._stop_agent is None:
            raise RuntimeError("Debugger stop control is not configured")
        result = await self._stop_agent(agent_id)
        if result:
            self._event_store.append(
                new_swarm_event(
                    "agent_finished",
                    agent_id=agent_id,
                    root_agent_id=self._root_agent_id(agent_id),
                    parent_agent_id=self._parent_agent_id(agent_id),
                    session_id=self._session_id(agent_id),
                    payload={"status": "stopped_by_debugger"},
                )
            )
        return result

    async def resolve_approval(self, correlation_id: str, *, status: str) -> dict[str, str]:
        """Record an approval decision in the event stream."""
        request_event = self._approval_event(correlation_id)
        if request_event is None:
            raise ValueError(f"No permission request found for correlation_id={correlation_id}")
        agent_id = request_event.agent_id
        response_mode = str(request_event.payload.get("response_mode", "legacy"))
        team_name = request_event.payload.get("team_name")
        if response_mode == "mailbox":
            worker_name = str(request_event.payload.get("worker_name", agent_id))
            await send_permission_response_via_mailbox(
                worker_name,
                PermissionResolution(
                    decision="approved" if status == "approved" else "rejected",
                    resolved_by="leader",
                    feedback=None if status == "approved" else status,
                ),
                correlation_id,
                str(team_name) if team_name is not None else None,
            )
        else:
            await send_permission_response(
                SwarmPermissionResponse(
                    request_id=correlation_id,
                    allowed=status == "approved",
                    feedback=None if status == "approved" else status,
                ),
                str(team_name) if team_name is not None else "default",
                str(request_event.payload.get("worker_id", agent_id)),
                str(request_event.payload.get("approver_id", request_event.root_agent_id)),
            )
        event = new_swarm_event(
            "permission_resolved",
            agent_id=agent_id,
            root_agent_id=self._root_agent_id(agent_id),
            parent_agent_id=self._parent_agent_id(agent_id),
            session_id=self._session_id(agent_id),
            correlation_id=correlation_id,
            payload={"status": status},
        )
        self._event_store.append(event)
        return {"correlation_id": correlation_id, "status": status}

    def apply_context_patch(
        self,
        agent_id: str,
        *,
        patch: dict[str, Any],
        base_version: int,
    ):
        """Apply a debugger context patch and emit editor-ready events."""
        self._event_store.append(
            new_swarm_event(
                "context_patch_requested",
                agent_id=agent_id,
                root_agent_id=self._root_agent_id(agent_id),
                parent_agent_id=self._parent_agent_id(agent_id),
                session_id=self._session_id(agent_id),
                payload={"patch": patch, "base_version": base_version},
            )
        )
        snapshot = self._context_registry.apply_patch(agent_id, patch=patch, base_version=base_version)
        self._event_store.append(
            new_swarm_event(
                "context_patch_applied",
                agent_id=agent_id,
                root_agent_id=self._root_agent_id(agent_id),
                parent_agent_id=self._parent_agent_id(agent_id),
                session_id=self._session_id(agent_id),
                payload={"context_version": snapshot.context_version},
            )
        )
        return snapshot

    def list_scenarios(self) -> tuple[str, ...]:
        """Return available deterministic manager scenarios."""
        return AgentManager(
            event_store=self._event_store,
            context_registry=self._context_registry,
        ).list_scenarios()

    def run_scenario(self, name: str) -> dict[str, object]:
        """Run one deterministic scenario through the agent manager."""
        return AgentManager(
            event_store=self._event_store,
            context_registry=self._context_registry,
        ).run_scenario(name)

    def _build_projection(self, events: tuple[SwarmEvent, ...]) -> SwarmProjection:
        projection = SwarmProjection()
        for event in events:
            projection.apply(event)
        return projection

    def _projection_payload(self, projection: SwarmProjection) -> dict[str, Any]:
        tree = projection.tree_snapshot()
        visible_agent_ids = set(tree["nodes"].keys())
        timeline = [event.to_dict() for event in projection.timeline()]
        contexts = {
            agent_id: snapshot
            for agent_id, snapshot in self._context_registry.all().items()
            if agent_id in visible_agent_ids
        }
        return {
            "tree": tree,
            "timeline": timeline,
            "message_graph": list(projection.message_graph()),
            "approval_queue": list(projection.approval_queue()),
            "contexts": contexts,
            "overview": self._build_overview(tree, timeline, projection.message_graph(), projection.approval_queue()),
            "activity": self._build_activity(tree, timeline, projection.message_graph()),
            "scenario_view": self._build_scenario_view(tree, projection.message_graph(), contexts),
        }

    def _root_agent_id(self, agent_id: str) -> str:
        snapshot = self._context_registry.get(agent_id)
        return snapshot.root_agent_id or agent_id if snapshot else agent_id

    def _parent_agent_id(self, agent_id: str) -> str | None:
        snapshot = self._context_registry.get(agent_id)
        return snapshot.parent_agent_id if snapshot else None

    def _session_id(self, agent_id: str) -> str | None:
        snapshot = self._context_registry.get(agent_id)
        return snapshot.session_id if snapshot else None

    def _approval_event(self, correlation_id: str) -> SwarmEvent | None:
        for event in reversed(self._event_store.all_events()):
            if event.correlation_id == correlation_id and event.event_type == "permission_requested":
                return event
        return None

    def _build_overview(
        self,
        tree: dict[str, Any],
        timeline: list[dict[str, Any]],
        message_graph: tuple[dict[str, str | None], ...],
        approval_queue: tuple[dict[str, str | None], ...],
    ) -> dict[str, Any]:
        nodes = tree["nodes"]
        depths = [len(node["lineage_path"]) for node in nodes.values()] or [0]
        leaf_agents = sorted(
            agent_id for agent_id, node in nodes.items()
            if not node["children"]
        )
        pending_approvals = sum(1 for item in approval_queue if item.get("status") == "pending")
        return {
            "agent_count": len(nodes),
            "root_count": len(tree["roots"]),
            "message_count": len(message_graph),
            "event_count": len(timeline),
            "pending_approvals": pending_approvals,
            "max_depth": max(depths),
            "leaf_agents": leaf_agents,
        }

    def _build_activity(
        self,
        tree: dict[str, Any],
        timeline: list[dict[str, Any]],
        message_graph: tuple[dict[str, str | None], ...],
    ) -> dict[str, Any]:
        grouped: dict[str, dict[str, Any]] = {}
        for agent_id, node in tree["nodes"].items():
            grouped[agent_id] = {
                "status": node["status"],
                "parent_agent_id": node["parent_agent_id"],
                "children": list(node["children"]),
                "event_counts": {},
                "recent_events": [],
                "messages_sent": 0,
                "messages_received": 0,
            }
        for event in timeline:
            agent_id = event["agent_id"]
            if agent_id not in grouped:
                continue
            counts = grouped[agent_id]["event_counts"]
            counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
            grouped[agent_id]["recent_events"].append(event["event_type"])
            grouped[agent_id]["recent_events"] = grouped[agent_id]["recent_events"][-5:]
        for edge in message_graph:
            sender = edge.get("from_agent")
            recipient = edge.get("to_agent")
            if sender in grouped:
                grouped[sender]["messages_sent"] += 1
            if recipient in grouped:
                grouped[recipient]["messages_received"] += 1
        return grouped

    def _build_scenario_view(
        self,
        tree: dict[str, Any],
        message_graph: tuple[dict[str, str | None], ...],
        contexts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        levels: dict[int, list[str]] = {}
        for agent_id, node in tree["nodes"].items():
            depth = len(node["lineage_path"])
            levels.setdefault(depth, []).append(agent_id)
        route_summary: dict[str, list[str]] = {}
        for edge in message_graph:
            sender = edge.get("from_agent")
            recipient = edge.get("to_agent")
            if sender is None or recipient is None:
                continue
            route_summary.setdefault(sender, [])
            if recipient not in route_summary[sender]:
                route_summary[sender].append(recipient)
        scenario_names = {
            (snapshot.get("metadata") or {}).get("scenario")
            for snapshot in contexts.values()
            if (snapshot.get("metadata") or {}).get("scenario")
        }
        return {
            "scenario_name": next(iter(scenario_names)) if len(scenario_names) == 1 else None,
            "levels": [
                {"depth": depth, "agents": sorted(agent_ids)}
                for depth, agent_ids in sorted(levels.items())
            ],
            "route_summary": {
                agent_id: sorted(children)
                for agent_id, children in route_summary.items()
            },
        }


def create_default_swarm_debugger_service() -> SwarmDebuggerService:
    """Create a debugger service wired to the live swarm runtime."""

    async def _send(agent_id: str, message: str) -> dict[str, Any]:
        snapshot = get_context_registry().get(agent_id)
        router = MessageRouter()
        return await router.route_message(
            target_agent_id=agent_id,
            message=TeammateMessage(text=message, from_agent="debugger@console"),
            parent_agent_id=snapshot.parent_agent_id if snapshot else None,
            root_agent_id=snapshot.root_agent_id or agent_id if snapshot else agent_id,
            session_id="debugger-console",
        )

    async def _pause(agent_id: str) -> bool:
        task_id = _latest_task_id_for_agent(agent_id)
        if task_id and load_persisted_task_record(task_id) is not None:
            await get_task_manager().pause_task(task_id)
            return True
        return False

    async def _resume(agent_id: str) -> bool:
        task_id = _latest_task_id_for_agent(agent_id)
        if task_id and load_persisted_task_record(task_id) is not None:
            await get_task_manager().resume_task(task_id)
            return True
        return False

    async def _stop(agent_id: str) -> bool:
        task_id = _latest_task_id_for_agent(agent_id)
        if task_id and load_persisted_task_record(task_id) is not None:
            await get_task_manager().stop_task(task_id)
            return True
        registry = get_backend_registry()
        for backend_type in ("in_process", "subprocess"):
            try:
                backend = registry.get_executor(backend_type)
            except KeyError:
                continue
            try:
                if await backend.shutdown(agent_id):
                    return True
            except Exception:
                continue
        return False

    return SwarmDebuggerService(
        send_message=_send,
        pause_agent=_pause,
        resume_agent=_resume,
        stop_agent=_stop,
    )


def _latest_task_id_for_agent(agent_id: str) -> str | None:
    for event in reversed(get_event_store().all_events()):
        if event.event_type == "agent_spawned" and event.agent_id == agent_id:
            task_id = event.payload.get("task_id")
            if task_id is not None:
                return str(task_id)
    return None
