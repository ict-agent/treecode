"""Debugger service for tree snapshots, playback, and control actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
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
from openharness.swarm.run_archive import RunArchiveStore
from openharness.swarm.topology_reader import (
    TopologyView,
    build_projection as build_topology_projection,
    live_runtime_state as build_live_runtime_state,
    materialize_topology,
)
from openharness.swarm.types import TeammateMessage
from openharness.tasks import get_task_manager
from openharness.tasks.manager import load_persisted_task_record
from openharness.permissions.checker import PermissionChecker
from openharness.config import load_settings
from openharness.tools.agent_tool import AgentTool, AgentToolInput
from openharness.tools.base import ToolExecutionContext, ToolRegistry, ToolResult
from openharness.tools import create_default_tool_registry

_AGENT_FEED_MAX = 80
_LIVE_MAIN_AGENT_ID = "main@default"
_LIVE_MAIN_PROMPT = (
    "You are the main coordinator agent for the OpenHarness live multi-agent console. "
    "Respond to user messages directly when appropriate, and spawn or coordinate subagents when useful. "
    "Stay available for follow-up messages."
)


class SwarmDebuggerService:
    """Aggregate runtime views and expose control operations for the web debugger."""

    def __init__(
        self,
        *,
        event_store: EventStore | None = None,
        context_registry: AgentContextRegistry | None = None,
        archive_dir: Any | None = None,
        cwd: str | Path | None = None,
        tool_registry: ToolRegistry | None = None,
        permission_checker: PermissionChecker | None = None,
        send_message: Callable[[str, str], Awaitable[dict[str, Any]]] | None = None,
        pause_agent: Callable[[str], Awaitable[bool]] | None = None,
        resume_agent: Callable[[str], Awaitable[bool]] | None = None,
        stop_agent: Callable[[str], Awaitable[bool]] | None = None,
        reconcile_live_runtime: bool = True,
        auto_bootstrap_live_main: bool = False,
    ) -> None:
        self._event_store = event_store or get_event_store()
        self._context_registry = context_registry or get_context_registry()
        self._scenario_event_store = EventStore()
        self._scenario_context_registry = AgentContextRegistry()
        self._active_source: str = "live"
        self._topology_view: TopologyView = "live"
        self._archive_store = RunArchiveStore(storage_dir=archive_dir)
        self._cwd = Path(cwd or Path.cwd()).resolve()
        self._tool_registry = tool_registry or create_default_tool_registry()
        self._permission_checker = permission_checker or PermissionChecker(load_settings().permission)
        self._send_message = send_message
        self._pause_agent = pause_agent
        self._resume_agent = resume_agent
        self._stop_agent = stop_agent
        self._reconcile_live_runtime = reconcile_live_runtime
        self._auto_bootstrap_live_main = auto_bootstrap_live_main
        self._snapshot_revision = 0

    def snapshot(self) -> dict[str, Any]:
        """Return the current debugger snapshot."""
        projection = self._build_projection(self._active_event_store().all_events())
        return self._projection_payload(projection, increment_revision=True)

    def change_token(self) -> tuple[str, int, str | None, str]:
        """Return a cheap token that changes when the active runtime view changes."""
        events = self._active_event_store().all_events()
        return (
            self._active_source,
            len(events),
            events[-1].event_id if events else None,
            self._topology_view,
        )

    def playback(self, *, event_limit: int | None = None) -> dict[str, Any]:
        """Return a replay snapshot reconstructed from the event log prefix."""
        events = self._event_store.all_events()
        if self._active_source == "scenario":
            events = self._scenario_event_store.all_events()
        if event_limit is not None:
            events = events[:event_limit]
        projection = self._build_projection(events)
        return self._projection_payload(projection, increment_revision=False)

    async def send_message(self, agent_id: str, message: str) -> dict[str, Any]:
        """Send a debugger-originated message into the runtime."""
        if self._send_message is None:
            raise RuntimeError("Debugger send_message control is not configured")
        resolved = self._resolve_agent_id_for_send(agent_id)
        result = await self._send_message(resolved, message)
        self._event_store_for_agent(resolved).append(
            new_swarm_event(
                "manual_message_injected",
                agent_id=resolved,
                root_agent_id=self._root_agent_id(resolved),
                parent_agent_id=self._parent_agent_id(resolved),
                session_id=self._session_id(resolved),
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
            self._event_store_for_agent(agent_id).append(
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
            self._event_store_for_agent(agent_id).append(
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
            self._event_store_for_agent(agent_id).append(
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
        self._event_store_for_agent(agent_id).append(event)
        return {"correlation_id": correlation_id, "status": status}

    def apply_context_patch(
        self,
        agent_id: str,
        *,
        patch: dict[str, Any],
        base_version: int,
    ):
        """Apply a debugger context patch and emit editor-ready events."""
        self._event_store_for_agent(agent_id).append(
            new_swarm_event(
                "context_patch_requested",
                agent_id=agent_id,
                root_agent_id=self._root_agent_id(agent_id),
                parent_agent_id=self._parent_agent_id(agent_id),
                session_id=self._session_id(agent_id),
                payload={"patch": patch, "base_version": base_version},
            )
        )
        event_store, context_registry = self._stores_for_agent(agent_id)
        snapshot = context_registry.apply_patch(agent_id, patch=patch, base_version=base_version)
        event_store.append(
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
            event_store=self._scenario_event_store,
            context_registry=self._scenario_context_registry,
        ).list_scenarios()

    def run_scenario(self, name: str) -> dict[str, object]:
        """Run one deterministic scenario through the agent manager."""
        self._active_source = "scenario"
        return AgentManager(
            event_store=self._scenario_event_store,
            context_registry=self._scenario_context_registry,
        ).run_scenario(name)

    def archive_current_run(self, *, label: str) -> dict[str, object]:
        """Persist the current snapshot and event stream as an archived run."""
        projection = self._build_projection(self._event_store.all_events())
        if self._active_source == "scenario":
            projection = self._build_projection(self._scenario_event_store.all_events())
        snapshot = self._projection_payload(projection, increment_revision=False)
        record = self._archive_store.archive_run(
            label=label,
            snapshot=snapshot,
            events=self._active_event_store().all_events(),
        )
        return record.to_dict()

    def list_archives(self) -> list[dict[str, object]]:
        """Return archived runs for dashboard browsing."""
        return self._archive_store.list_archives()

    def compare_runs(self, left_run_id: str, right_run_id: str) -> dict[str, object]:
        """Compare two archived runs."""
        return self._archive_store.compare_runs(left_run_id, right_run_id)

    def set_active_source(self, source: str) -> dict[str, str]:
        """Switch between live and scenario snapshots."""
        if source not in {"live", "scenario"}:
            raise ValueError(f"Unknown source: {source}")
        if source == "scenario" and not self._scenario_event_store.all_events():
            raise ValueError("No scenario data is currently loaded")
        self._active_source = source
        return {"active_source": source}

    def set_topology_view(self, view: str) -> dict[str, str]:
        """Switch between the filtered live tree and raw event topology."""
        if view not in {"live", "raw_events"}:
            raise ValueError(f"Unknown topology view: {view}")
        self._topology_view = view
        return {"topology_view": view}

    async def spawn_agent(
        self,
        *,
        agent_id: str,
        prompt: str,
        parent_agent_id: str | None = None,
        mode: str = "synthetic",
    ) -> dict[str, object]:
        """Create a new agent either synthetically or via the live tool path."""
        if not str(agent_id).strip():
            raise ValueError(
                "agent_id is required. Empty ids collapse multiple children to the same swarm identity."
            )
        if mode == "live":
            parent = None
            if parent_agent_id:
                parent = self._context_for_agent(parent_agent_id)
                if parent is None:
                    raise ValueError(f"Unknown parent agent: {parent_agent_id}")
            elif not self._is_live_main_identifier(agent_id):
                await self.ensure_live_main()
                parent = self._context_for_agent(_LIVE_MAIN_AGENT_ID)
            result = await self._spawn_live_agent(agent_id=agent_id, prompt=prompt, parent=parent)
            return {"agent_id": agent_id, "mode": "live", "output": result.output}

        self._active_source = "scenario"
        return AgentManager(
            event_store=self._scenario_event_store,
            context_registry=self._scenario_context_registry,
        ).spawn_synthetic_agent(
            agent_id,
            parent_agent_id=parent_agent_id,
            prompt=prompt,
        )

    def reparent_agent(self, agent_id: str, new_parent_agent_id: str | None) -> dict[str, object]:
        """Reparent one agent in the current debugger tree."""
        target_event_store, target_context_registry = self._stores_for_agent(agent_id)
        return AgentManager(
            event_store=target_event_store,
            context_registry=target_context_registry,
        ).reparent_agent(agent_id, new_parent_agent_id)

    async def remove_agent(self, agent_id: str) -> dict[str, object]:
        """Remove an agent from the current debugger tree."""
        snapshot = self._context_for_agent(agent_id)
        if snapshot is not None and snapshot.metadata and snapshot.metadata.get("synthetic"):
            target_event_store, target_context_registry = self._stores_for_agent(agent_id)
            self._active_source = "scenario"
            return AgentManager(
                event_store=target_event_store,
                context_registry=target_context_registry,
            ).remove_agent(agent_id)
        if snapshot is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        root_agent_id = snapshot.root_agent_id or agent_id
        parent_agent_id = snapshot.parent_agent_id
        session_id = snapshot.session_id
        stopped = await self.stop_agent(agent_id)
        if not stopped:
            raise ValueError(f"Failed to stop agent before removal: {agent_id}")
        _, context_registry = self._stores_for_agent(agent_id)
        context_registry.remove(agent_id)
        self._event_store_for_agent(agent_id).append(
            new_swarm_event(
                "agent_removed",
                agent_id=agent_id,
                root_agent_id=root_agent_id,
                parent_agent_id=parent_agent_id,
                session_id=session_id,
            )
        )
        return {"agent_id": agent_id, "removed": True}

    async def run_agent_action(
        self,
        *,
        agent_id: str,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one generic operation against an agent."""
        if action == "inspect":
            snapshot = self.snapshot()
            return {
                "agent_id": agent_id,
                "node": snapshot["tree"]["nodes"].get(agent_id),
                "context": snapshot["contexts"].get(agent_id),
                "activity": snapshot["activity"].get(agent_id),
            }
        if action == "send_message":
            return await self.send_message(agent_id, str(params.get("message", "")))
        if action == "pause":
            return {"ok": await self.pause_agent(agent_id)}
        if action == "resume":
            return {"ok": await self.resume_agent(agent_id)}
        if action == "stop":
            return {"ok": await self.stop_agent(agent_id)}
        if action == "spawn_child":
            return await self.spawn_agent(
                agent_id=str(params["child_agent_id"]),
                prompt=str(params["prompt"]),
                parent_agent_id=agent_id,
                mode=str(params.get("mode", "synthetic")),
            )
        if action == "reparent":
            return self.reparent_agent(
                agent_id,
                params.get("new_parent_agent_id") and str(params["new_parent_agent_id"]) or None,
            )
        if action == "remove":
            return await self.remove_agent(agent_id)
        if action == "patch_context":
            snapshot = self.apply_context_patch(
                agent_id,
                base_version=int(params["base_version"]),
                patch=dict(params.get("patch", {})),
            )
            return snapshot.to_dict()
        if action == "run_tool":
            return await self.execute_tool_for_agent(
                agent_id=agent_id,
                tool_name=str(params["tool_name"]),
                tool_input=dict(params.get("tool_input", {})),
            )
        raise ValueError(f"Unknown agent action: {action}")

    async def execute_tool_for_agent(
        self,
        *,
        agent_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one tool on behalf of an agent through the shared tool registry."""
        snapshot = self._context_for_agent(agent_id)
        if snapshot is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        tool = self._tool_registry.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name}")
        parsed_input = tool.input_model.model_validate(tool_input)
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "") or None
        command = str(tool_input.get("command") or "") or None
        decision = self._permission_checker.evaluate(
            tool_name,
            is_read_only=tool.is_read_only(parsed_input),
            file_path=file_path,
            command=command,
        )
        if not decision.allowed:
            raise ValueError(decision.reason or f"Permission denied for {tool_name}")
        self._event_store_for_agent(agent_id).append(
            new_swarm_event(
                "tool_called",
                agent_id=agent_id,
                root_agent_id=snapshot.root_agent_id or agent_id,
                parent_agent_id=snapshot.parent_agent_id,
                session_id=snapshot.session_id,
                payload={"tool_name": tool_name, "tool_input": tool_input, "source": "console"},
            )
        )
        result = await tool.execute(
            parsed_input,
            ToolExecutionContext(
                cwd=self._cwd,
                metadata={
                    "session_id": snapshot.session_id,
                    "swarm_agent_id": snapshot.agent_id,
                    "swarm_root_agent_id": snapshot.root_agent_id or snapshot.agent_id,
                    "swarm_lineage_path": snapshot.lineage_path,
                    "tool_registry": self._tool_registry,
                },
            ),
        )
        self._event_store_for_agent(agent_id).append(
            new_swarm_event(
                "tool_completed",
                agent_id=agent_id,
                root_agent_id=snapshot.root_agent_id or agent_id,
                parent_agent_id=snapshot.parent_agent_id,
                session_id=snapshot.session_id,
                payload={
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "is_error": result.is_error,
                    "output": result.output,
                    "source": "console",
                },
            )
        )
        return {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "output": result.output,
            "is_error": result.is_error,
        }

    def _build_projection(self, events: tuple[SwarmEvent, ...]) -> SwarmProjection:
        return build_topology_projection(events)

    def _projection_payload(self, projection: SwarmProjection, *, increment_revision: bool) -> dict[str, Any]:
        topology = materialize_topology(
            projection,
            view=self._topology_view,
            runtime_state_provider=(
                build_live_runtime_state if self._active_source == "live" and self._reconcile_live_runtime else None
            ),
        )
        tree = topology.tree
        visible_agent_ids = set(topology.visible_agent_ids)
        filtered_timeline = tuple(event for event in topology.timeline if event.agent_id in visible_agent_ids)
        timeline = [event.to_dict() for event in filtered_timeline]
        message_graph = tuple(
            edge
            for edge in projection.message_graph()
            if edge.get("from_agent") in visible_agent_ids or edge.get("to_agent") in visible_agent_ids
        )
        approval_queue = tuple(
            item for item in projection.approval_queue() if item.get("agent_id") in visible_agent_ids
        )
        tool_recent = tuple(
            item for item in projection.tool_recent() if item.get("agent_id") in visible_agent_ids
        )
        active_contexts = (
            self._scenario_context_registry.all()
            if self._active_source == "scenario"
            else self._context_registry.all()
        )
        contexts = {
            agent_id: snapshot
            for agent_id, snapshot in active_contexts.items()
            if agent_id in visible_agent_ids
        }
        activity = self._build_activity(tree, timeline, message_graph)
        agent_feeds = self._build_agent_feeds(
            filtered_timeline,
            visible_agent_ids=visible_agent_ids,
            contexts=contexts,
        )
        agents = self._build_agents(
            tree=tree,
            activity=activity,
            contexts=contexts,
            agent_feeds=agent_feeds,
        )
        if increment_revision:
            self._snapshot_revision += 1
        return {
            "snapshot_revision": self._snapshot_revision,
            "topology_view": self._topology_view,
            "available_topology_views": ["live", "raw_events"],
            "tree": tree,
            "timeline": timeline,
            "message_graph": list(message_graph),
            "tool_recent": list(tool_recent),
            "approval_queue": list(approval_queue),
            "contexts": contexts,
            "agents": agents,
            "overview": self._build_overview(tree, timeline, message_graph, approval_queue),
            "activity": activity,
            "scenario_view": self._build_scenario_view(tree, message_graph, contexts),
            "archives": self._archive_store.list_archives(),
            "active_source": self._active_source,
            "available_sources": [
                source
                for source in ("live", "scenario")
                if source == "live" or self._scenario_event_store.all_events()
            ],
        }

    def _root_agent_id(self, agent_id: str) -> str:
        snapshot = self._context_for_agent(agent_id)
        return snapshot.root_agent_id or agent_id if snapshot else agent_id

    def _parent_agent_id(self, agent_id: str) -> str | None:
        snapshot = self._context_for_agent(agent_id)
        return snapshot.parent_agent_id if snapshot else None

    def _session_id(self, agent_id: str) -> str | None:
        snapshot = self._context_for_agent(agent_id)
        return snapshot.session_id if snapshot else None

    def _approval_event(self, correlation_id: str) -> SwarmEvent | None:
        for event in reversed(self._active_event_store().all_events()):
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

    def _build_agents(
        self,
        *,
        tree: dict[str, Any],
        activity: dict[str, Any],
        contexts: dict[str, dict[str, Any]],
        agent_feeds: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        agents: dict[str, dict[str, Any]] = {}
        for agent_id, node in tree["nodes"].items():
            context = contexts.get(agent_id, {})
            metadata = context.get("metadata") or {}
            summary = activity.get(agent_id, {})
            raw_messages = context.get("messages")
            messages = list(raw_messages) if isinstance(raw_messages, (list, tuple)) else []
            agents[agent_id] = {
                "agent_id": agent_id,
                "name": node.get("name", agent_id.split("@", 1)[0]),
                "team": node.get("team", agent_id.split("@", 1)[1] if "@" in agent_id else "default"),
                "status": node.get("status", "unknown"),
                "parent_agent_id": node.get("parent_agent_id"),
                "root_agent_id": node.get("root_agent_id"),
                "session_id": node.get("session_id"),
                "lineage_path": list(node.get("lineage_path", [])),
                "children": list(node.get("children", [])),
                "cwd": node.get("cwd"),
                "worktree_path": node.get("worktree_path"),
                "backend_type": node.get("backend_type"),
                "spawn_mode": node.get("spawn_mode"),
                "synthetic": bool(node.get("synthetic", False) or metadata.get("synthetic", False)),
                "scenario_name": metadata.get("scenario"),
                "prompt": context.get("prompt"),
                "system_prompt": context.get("system_prompt"),
                "context_version": context.get("context_version"),
                "compacted_summary": context.get("compacted_summary"),
                "messages": messages,
                "messages_sent": summary.get("messages_sent", 0),
                "messages_received": summary.get("messages_received", 0),
                "recent_events": list(summary.get("recent_events", [])),
                "event_counts": dict(summary.get("event_counts", {})),
                "feed": list(agent_feeds.get(agent_id, [])),
            }
        return agents

    def _build_agent_feeds(
        self,
        events: tuple[SwarmEvent, ...],
        *,
        visible_agent_ids: set[str],
        contexts: dict[str, dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        feeds = {agent_id: [] for agent_id in visible_agent_ids}
        for agent_id, snapshot in contexts.items():
            prompt = str(snapshot.get("prompt", "") or "").strip()
            if not prompt:
                continue
            feeds.setdefault(agent_id, []).append(
                {
                    "item_id": f"{agent_id}:prompt",
                    "item_type": "prompt",
                    "event_type": "prompt",
                    "timestamp": None,
                    "correlation_id": None,
                    "actor": "task",
                    "label": "Task prompt",
                    "text": prompt,
                }
            )
        for event in events:
            if event.agent_id not in visible_agent_ids:
                continue
            item = self._event_to_feed_item(event)
            if item is None:
                continue
            feeds.setdefault(event.agent_id, []).append(item)
        for agent_id, items in list(feeds.items()):
            prompt_items = [item for item in items if item["item_type"] == "prompt"][:1]
            other_items = [item for item in items if item["item_type"] != "prompt"]
            if len(other_items) > _AGENT_FEED_MAX:
                other_items = other_items[-_AGENT_FEED_MAX:]
            feeds[agent_id] = prompt_items + other_items
        return feeds

    def _event_to_feed_item(self, event: SwarmEvent) -> dict[str, Any] | None:
        payload = event.payload
        base = {
            "item_id": event.event_id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "correlation_id": event.correlation_id,
        }
        if event.event_type == "turn_started":
            return {
                **base,
                "item_type": "turn_marker",
                "actor": "system",
                "label": "Turn started",
                "message_count": int(payload.get("message_count", 0)),
                "text": f"Context contains {int(payload.get('message_count', 0))} messages.",
            }
        if event.event_type in {"message_delivered", "manual_message_injected"}:
            source = (
                "debugger"
                if event.event_type == "manual_message_injected"
                else str(payload.get("from_agent", "unknown"))
            )
            text = (
                str(payload.get("message", ""))
                if event.event_type == "manual_message_injected"
                else str(payload.get("text", ""))
            )
            return {
                **base,
                "item_type": "incoming",
                "actor": source,
                "label": source,
                "text": text,
                "route_kind": payload.get("route_kind"),
            }
        if event.event_type == "assistant_message":
            return {
                **base,
                "item_type": "assistant",
                "actor": event.agent_id,
                "label": "assistant",
                "text": str(payload.get("text", "")),
                "has_tool_uses": bool(payload.get("has_tool_uses", False)),
            }
        if event.event_type == "tool_called":
            tool_name = str(payload.get("tool_name", "tool"))
            return {
                **base,
                "item_type": "tool_call",
                "actor": tool_name,
                "label": tool_name,
                "tool_name": tool_name,
                "tool_input": payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {},
                "source": payload.get("source"),
            }
        if event.event_type == "tool_completed":
            tool_name = str(payload.get("tool_name", "tool"))
            return {
                **base,
                "item_type": "tool_result",
                "actor": tool_name,
                "label": tool_name,
                "tool_name": tool_name,
                "text": str(payload.get("output", "")),
                "is_error": bool(payload.get("is_error", False)),
                "source": payload.get("source"),
            }
        if event.event_type == "permission_requested":
            tool_name = str(payload.get("tool_name", "approval"))
            return {
                **base,
                "item_type": "approval_request",
                "actor": tool_name,
                "label": "approval requested",
                "tool_name": tool_name,
                "status": str(payload.get("status", "pending")),
            }
        if event.event_type == "permission_resolved":
            return {
                **base,
                "item_type": "approval_result",
                "actor": "approval",
                "label": "approval resolved",
                "status": str(payload.get("status", "resolved")),
                "text": str(payload.get("status", "resolved")),
            }
        if event.event_type in {
            "agent_spawned",
            "agent_became_running",
            "agent_paused",
            "agent_resumed",
            "agent_finished",
            "agent_removed",
        }:
            return {
                **base,
                "item_type": "lifecycle",
                "actor": "system",
                "label": event.event_type.replace("_", " "),
                "status": payload.get("status"),
                "text": self._lifecycle_text(event),
            }
        if event.event_type in {"context_patch_applied", "context_patch_rejected"}:
            return {
                **base,
                "item_type": "context",
                "actor": "context",
                "label": event.event_type.replace("_", " "),
                "text": str(payload.get("context_version", payload.get("reason", ""))),
            }
        return None

    @staticmethod
    def _lifecycle_text(event: SwarmEvent) -> str:
        status = event.payload.get("status")
        if event.event_type == "agent_spawned":
            return "Agent was created."
        if event.event_type == "agent_became_running":
            return f"Agent is running{f' ({status})' if status else ''}."
        if event.event_type == "agent_paused":
            return "Agent was paused."
        if event.event_type == "agent_resumed":
            return "Agent resumed execution."
        if event.event_type == "agent_finished":
            return f"Agent finished{f' ({status})' if status else ''}."
        if event.event_type == "agent_removed":
            return "Agent was removed from the tree."
        return event.event_type.replace("_", " ")

    def _context_for_agent(self, agent_id: str):
        return self._scenario_context_registry.get(agent_id) or self._context_registry.get(agent_id)

    async def ensure_live_main(self) -> str:
        """Ensure the default live root agent exists and is recoverable."""
        runtime_state = build_live_runtime_state(self._event_store.all_events())
        if _LIVE_MAIN_AGENT_ID in runtime_state and self._context_registry.get(_LIVE_MAIN_AGENT_ID) is not None:
            self._active_source = "live"
            return _LIVE_MAIN_AGENT_ID

        await self._spawn_live_agent(agent_id="main", prompt=_LIVE_MAIN_PROMPT, parent=None)
        return _LIVE_MAIN_AGENT_ID

    async def maybe_ensure_live_main(self) -> str | None:
        """Best-effort live main bootstrap for the default console workflow."""
        if not self._auto_bootstrap_live_main:
            return None
        return await self.ensure_live_main()

    async def _spawn_live_agent(
        self,
        *,
        agent_id: str,
        prompt: str,
        parent,
    ) -> ToolResult:
        canonical_agent_id = self._canonical_agent_id(agent_id)
        metadata: dict[str, object] = {}
        if parent is not None:
            metadata = {
                "session_id": parent.session_id,
                "swarm_agent_id": parent.agent_id,
                "swarm_root_agent_id": parent.root_agent_id or parent.agent_id,
                "swarm_lineage_path": parent.lineage_path,
            }
        result = await AgentTool().execute(
            AgentToolInput(
                description=f"Spawn {canonical_agent_id} from web console",
                prompt=prompt,
                subagent_type=canonical_agent_id.split("@", 1)[0],
                team=canonical_agent_id.split("@", 1)[1],
                spawn_mode="persistent",
            ),
            ToolExecutionContext(cwd=self._cwd, metadata=metadata),
        )
        if result.is_error:
            raise ValueError(result.output)
        self._active_source = "live"
        return result

    @staticmethod
    def _canonical_agent_id(agent_id: str) -> str:
        raw = agent_id.strip()
        if not raw:
            raise ValueError(
                "agent_id is required for each subagent. "
                "Use a unique id per spawn (e.g. analyst, worker-b, researcher@backend). "
                "Leaving the field empty maps every child to agent@default and overwrites the previous one."
            )
        if "@" in raw:
            name, _, rest = raw.partition("@")
            name = name.strip()
            rest = rest.strip()
            if not name:
                raise ValueError(
                    f"agent_id must include a non-empty name before '@' (got {agent_id!r})."
                )
            if not rest:
                raise ValueError(
                    f"agent_id must include a team after '@', or omit '@' to use @default (got {agent_id!r})."
                )
            return f"{name}@{rest}"
        return f"{raw}@default"

    @staticmethod
    def _is_live_main_identifier(agent_id: str) -> bool:
        return agent_id in {"main", _LIVE_MAIN_AGENT_ID}

    def _resolve_agent_id_for_send(self, agent_id: str) -> str:
        """Map debugger input (e.g. ``main@default``) to the id used in scenario/live registries."""
        active_registry = (
            self._scenario_context_registry if self._active_source == "scenario" else self._context_registry
        )
        if active_registry.get(agent_id) is not None:
            return agent_id
        if agent_id.endswith("@default"):
            bare = agent_id.split("@", 1)[0]
            if active_registry.get(bare) is not None:
                return bare
        if self._context_for_agent(agent_id) is not None:
            return agent_id
        if agent_id.endswith("@default"):
            bare = agent_id.split("@", 1)[0]
            if self._context_for_agent(bare) is not None:
                return bare
        return agent_id

    def _stores_for_agent(self, agent_id: str) -> tuple[EventStore, AgentContextRegistry]:
        if self._scenario_context_registry.get(agent_id) is not None:
            return self._scenario_event_store, self._scenario_context_registry
        return self._event_store, self._context_registry

    def _event_store_for_agent(self, agent_id: str) -> EventStore:
        return self._stores_for_agent(agent_id)[0]

    def _active_event_store(self) -> EventStore:
        return self._scenario_event_store if self._active_source == "scenario" else self._event_store

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


def create_default_swarm_debugger_service(*, cwd: str | Path | None = None) -> SwarmDebuggerService:
    """Create a debugger service wired to the live swarm runtime."""

    _send_service: list[SwarmDebuggerService | None] = [None]

    async def _send(agent_id: str, message: str) -> dict[str, Any]:
        svc = _send_service[0]
        if svc is None:
            raise RuntimeError("Swarm debugger service is not initialized")
        snapshot = svc._context_for_agent(agent_id)
        store = svc._event_store_for_agent(agent_id)
        router = MessageRouter()
        session_id = (snapshot.session_id if snapshot else None) or "debugger-console"
        return await router.route_message(
            target_agent_id=agent_id,
            message=TeammateMessage(text=message, from_agent="debugger@console"),
            parent_agent_id=snapshot.parent_agent_id if snapshot else None,
            root_agent_id=(snapshot.root_agent_id or agent_id) if snapshot else agent_id,
            session_id=session_id,
            event_store=store,
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

    service = SwarmDebuggerService(
        cwd=cwd,
        send_message=_send,
        pause_agent=_pause,
        resume_agent=_resume,
        stop_agent=_stop,
        reconcile_live_runtime=True,
        auto_bootstrap_live_main=True,
    )
    _send_service[0] = service
    return service


def _latest_task_id_for_agent(agent_id: str) -> str | None:
    for event in reversed(get_event_store().all_events()):
        if event.event_type == "agent_spawned" and event.agent_id == agent_id:
            task_id = event.payload.get("task_id")
            if task_id is not None:
                return str(task_id)
    return None
