"""Tracked context snapshots for debugger inspection and future runtime edits."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Any

from openharness.config.paths import get_data_dir


@dataclass(frozen=True)
class AgentContextSnapshot:
    """Serializable view of one agent's effective context."""

    agent_id: str
    session_id: str
    parent_agent_id: str | None = None
    root_agent_id: str | None = None
    lineage_path: tuple[str, ...] = ()
    prompt: str = ""
    system_prompt: str | None = None
    messages: tuple[str, ...] = ()
    compacted_summary: str | None = None
    context_version: int = 1
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return asdict(self)


class AgentContextRegistry:
    """In-memory registry of context snapshots keyed by agent ID."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._snapshots: dict[str, AgentContextSnapshot] = {}
        self._storage_dir = storage_dir
        if self._storage_dir is not None:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._reload_from_disk()

    def register(self, snapshot: AgentContextSnapshot) -> AgentContextSnapshot:
        """Insert or replace an agent snapshot."""
        self._snapshots[snapshot.agent_id] = snapshot
        self._persist(snapshot)
        return snapshot

    def get(self, agent_id: str) -> AgentContextSnapshot | None:
        """Return one context snapshot."""
        self._reload_from_disk()
        return self._snapshots.get(agent_id)

    def all(self) -> dict[str, dict[str, Any]]:
        """Return all snapshots in JSON-friendly form."""
        self._reload_from_disk()
        return {
            agent_id: snapshot.to_dict()
            for agent_id, snapshot in self._snapshots.items()
        }

    def apply_patch(
        self,
        agent_id: str,
        *,
        patch: dict[str, Any],
        base_version: int,
    ) -> AgentContextSnapshot:
        """Apply a versioned patch and bump the context version."""
        snapshot = self._snapshots[agent_id]
        if snapshot.context_version != base_version:
            raise ValueError(
                f"Context version mismatch for {agent_id}: expected {snapshot.context_version}, got {base_version}"
            )
        updated = replace(
            snapshot,
            messages=tuple(patch.get("messages", snapshot.messages)),
            compacted_summary=patch.get("compacted_summary", snapshot.compacted_summary),
            prompt=patch.get("prompt", snapshot.prompt),
            system_prompt=patch.get("system_prompt", snapshot.system_prompt),
            context_version=snapshot.context_version + 1,
        )
        self._snapshots[agent_id] = updated
        self._persist(updated)
        return updated

    def clear(self) -> None:
        """Remove all snapshots from memory and disk."""
        self._snapshots.clear()
        if self._storage_dir is None:
            return
        for path in self._storage_dir.glob("*.json"):
            path.unlink()

    def remove(self, agent_id: str) -> None:
        """Remove one snapshot from memory and disk."""
        self._snapshots.pop(agent_id, None)
        if self._storage_dir is None:
            return
        path = self._storage_dir / f"{agent_id.replace('/', '_')}.json"
        if path.exists():
            path.unlink()

    def snapshots(self) -> dict[str, AgentContextSnapshot]:
        """Return the current snapshots keyed by agent ID."""
        self._reload_from_disk()
        return dict(self._snapshots)

    def _persist(self, snapshot: AgentContextSnapshot) -> None:
        if self._storage_dir is None:
            return
        path = self._storage_dir / f"{snapshot.agent_id.replace('/', '_')}.json"
        path.write_text(json.dumps(snapshot.to_dict()), encoding="utf-8")

    def _reload_from_disk(self) -> None:
        if self._storage_dir is None:
            return
        snapshots: dict[str, AgentContextSnapshot] = {}
        for path in self._storage_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            snapshot = AgentContextSnapshot(
                **{
                    **data,
                    "lineage_path": tuple(data.get("lineage_path", [])),
                    "messages": tuple(data.get("messages", [])),
                }
            )
            snapshots[snapshot.agent_id] = snapshot
        self._snapshots = snapshots


_DEFAULT_CONTEXT_REGISTRY = AgentContextRegistry(storage_dir=get_data_dir() / "swarm" / "contexts")


def get_context_registry() -> AgentContextRegistry:
    """Return the process-wide context registry."""
    return _DEFAULT_CONTEXT_REGISTRY
