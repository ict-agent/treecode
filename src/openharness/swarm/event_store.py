"""Append-only storage for structured swarm events."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import threading

from openharness.config.paths import get_data_dir
from openharness.swarm.events import SwarmEvent


@dataclass
class EventStore:
    """In-memory append-only event log for the current process."""

    _events: list[SwarmEvent] = field(default_factory=list)
    storage_path: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.storage_path is not None:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            if self.storage_path.exists():
                with self._lock:
                    self._events = [
                        SwarmEvent.from_dict(json.loads(line))
                        for line in self.storage_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]

    def append(self, event: SwarmEvent) -> None:
        """Append one event to the log."""
        with self._lock:
            self._events.append(event)
            if self.storage_path is not None:
                with self.storage_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event.to_dict()) + "\n")

    def all_events(self) -> tuple[SwarmEvent, ...]:
        """Return the full event stream in append order."""
        with self._lock:
            return tuple(self._events)

    def events_for_agent(self, agent_id: str) -> tuple[SwarmEvent, ...]:
        """Return all events for a specific agent."""
        return tuple(event for event in self._events if event.agent_id == agent_id)

    def latest_event(self, agent_id: str) -> SwarmEvent | None:
        """Return the most recent event for an agent, if any."""
        for event in reversed(self._events):
            if event.agent_id == agent_id:
                return event
        return None

    def clear(self) -> None:
        """Remove all events from the store."""
        with self._lock:
            self._events.clear()
            if self.storage_path is not None and self.storage_path.exists():
                self.storage_path.unlink()


_GLOBAL_EVENT_STORE = EventStore(storage_path=get_data_dir() / "swarm" / "events.jsonl")


def get_event_store() -> EventStore:
    """Return the process-wide swarm event store."""
    return _GLOBAL_EVENT_STORE
