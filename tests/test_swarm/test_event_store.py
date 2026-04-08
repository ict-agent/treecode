"""Tests for multi-process-safe swarm event store file access."""

from __future__ import annotations

import json

from openharness.swarm import event_store as event_store_module
from openharness.swarm.event_store import EventStore
from openharness.swarm.events import new_swarm_event


def test_event_store_append_uses_exclusive_file_lock(tmp_path, monkeypatch):
    calls: list[tuple[int, int]] = []

    class FakeFcntl:
        LOCK_SH = 1
        LOCK_EX = 2
        LOCK_UN = 8

        @staticmethod
        def flock(fd: int, operation: int) -> None:
            calls.append((fd, operation))

    monkeypatch.setattr(event_store_module, "fcntl", FakeFcntl, raising=False)
    store = EventStore(storage_path=tmp_path / "swarm" / "events.jsonl")
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="leader-session",
            payload={"name": "leader", "team": "demo"},
        )
    )

    assert any(operation == FakeFcntl.LOCK_EX for _, operation in calls)
    assert calls[-1][1] == FakeFcntl.LOCK_UN


def test_event_store_reload_uses_shared_file_lock(tmp_path, monkeypatch):
    calls: list[tuple[int, int]] = []

    class FakeFcntl:
        LOCK_SH = 1
        LOCK_EX = 2
        LOCK_UN = 8

        @staticmethod
        def flock(fd: int, operation: int) -> None:
            calls.append((fd, operation))

    event = new_swarm_event(
        "agent_spawned",
        agent_id="leader@demo",
        root_agent_id="leader@demo",
        session_id="leader-session",
        payload={"name": "leader", "team": "demo"},
    )
    storage_path = tmp_path / "swarm" / "events.jsonl"
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(json.dumps(event.to_dict()) + "\n", encoding="utf-8")

    monkeypatch.setattr(event_store_module, "fcntl", FakeFcntl, raising=False)
    store = EventStore(storage_path=storage_path)
    calls.clear()

    reloaded = store.all_events()

    assert len(reloaded) == 1
    assert any(operation == FakeFcntl.LOCK_SH for _, operation in calls)
    assert calls[-1][1] == FakeFcntl.LOCK_UN
