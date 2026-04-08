"""Append-only storage for structured swarm events."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

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
            self._reload_from_disk()

    def append(self, event: SwarmEvent) -> None:
        """Append one event to the log."""
        with self._lock:
            if self.storage_path is not None:
                with self._locked_file(self.storage_path, "a", lock_type=_lock_exclusive()) as handle:
                    handle.write(json.dumps(event.to_dict()) + "\n")
                    handle.flush()
            self._events.append(event)

    def all_events(self) -> tuple[SwarmEvent, ...]:
        """Return the full event stream in append order."""
        self._reload_from_disk()
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

    def _reload_from_disk(self) -> None:
        if self.storage_path is None or not self.storage_path.exists():
            return
        with self._lock:
            with self._locked_file(self.storage_path, "r", lock_type=_lock_shared()) as handle:
                self._events = [
                    SwarmEvent.from_dict(json.loads(line))
                    for line in handle.read().splitlines()
                    if line.strip()
                ]

    @staticmethod
    @contextmanager
    def _locked_file(path: Path, mode: str, *, lock_type: int | None) -> Iterator[object]:
        with path.open(mode, encoding="utf-8") as handle:
            if fcntl is not None and lock_type is not None:
                fcntl.flock(handle.fileno(), lock_type)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), _lock_unlock())


def _lock_shared() -> int | None:
    return None if fcntl is None else fcntl.LOCK_SH


def _lock_exclusive() -> int | None:
    return None if fcntl is None else fcntl.LOCK_EX


def _lock_unlock() -> int | None:
    return None if fcntl is None else fcntl.LOCK_UN


_GLOBAL_EVENT_STORE = EventStore(storage_path=get_data_dir() / "swarm" / "events.jsonl")


def get_event_store() -> EventStore:
    """Return the process-wide swarm event store."""
    return _GLOBAL_EVENT_STORE
