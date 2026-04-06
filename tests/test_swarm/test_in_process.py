"""Tests for InProcessBackend: spawn, shutdown, send_message, and contextvars."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openharness.swarm.event_store import get_event_store
from openharness.swarm.in_process import (
    InProcessBackend,
    TeammateContext,
    TeammateAbortController,
    get_teammate_context,
    start_in_process_teammate,
    set_teammate_context,
)
from openharness.swarm.types import TeammateMessage, TeammateSpawnConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spawn_config():
    return TeammateSpawnConfig(
        name="worker",
        team="test-team",
        prompt="hello",
        cwd="/tmp",
        parent_session_id="sess-001",
    )


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("OPENHARNESS_TEAMMATE_USE_STUB", "1")
    return InProcessBackend()


# ---------------------------------------------------------------------------
# TeammateContext
# ---------------------------------------------------------------------------


def test_teammate_context_defaults():
    ctx = TeammateContext(
        agent_id="w@t",
        agent_name="w",
        team_name="t",
    )
    assert ctx.color is None
    assert ctx.plan_mode_required is False
    assert not ctx.cancel_event.is_set()


# ---------------------------------------------------------------------------
# ContextVar get / set
# ---------------------------------------------------------------------------


def test_get_teammate_context_returns_none_outside_task():
    # Outside any async task, the contextvar should be None
    result = get_teammate_context()
    assert result is None


async def test_set_and_get_teammate_context():
    ctx = TeammateContext(agent_id="x@y", agent_name="x", team_name="y")
    set_teammate_context(ctx)
    assert get_teammate_context() is ctx


# ---------------------------------------------------------------------------
# InProcessBackend.spawn
# ---------------------------------------------------------------------------


async def test_spawn_returns_success_result(backend, spawn_config):
    result = await backend.spawn(spawn_config)
    assert result.success is True
    assert result.agent_id == "worker@test-team"
    assert result.backend_type == "in_process"
    assert result.task_id.startswith("in_process_")


async def test_spawn_duplicate_returns_failure(backend, spawn_config):
    await backend.spawn(spawn_config)
    # Spawn again while first is still running
    result = await backend.spawn(spawn_config)
    assert result.success is False
    assert result.error is not None


async def test_spawn_creates_active_agent(backend, spawn_config):
    await backend.spawn(spawn_config)
    assert backend.is_active("worker@test-team")


# ---------------------------------------------------------------------------
# InProcessBackend.shutdown
# ---------------------------------------------------------------------------


async def test_shutdown_unknown_agent_returns_false(backend):
    result = await backend.shutdown("nonexistent@team")
    assert result is False


async def test_graceful_shutdown(backend, spawn_config):
    await backend.spawn(spawn_config)
    assert backend.is_active("worker@test-team")

    result = await backend.shutdown("worker@test-team", timeout=2.0)
    assert result is True
    assert not backend.is_active("worker@test-team")


async def test_force_shutdown(backend, spawn_config):
    await backend.spawn(spawn_config)
    result = await backend.shutdown("worker@test-team", force=True, timeout=2.0)
    assert result is True


# ---------------------------------------------------------------------------
# InProcessBackend.send_message
# ---------------------------------------------------------------------------


async def test_send_message_delivers_to_running_teammate_queue(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = TeammateSpawnConfig(
        name="rcvr",
        team="myteam",
        prompt="wait",
        cwd="/tmp",
        parent_session_id="s",
    )
    await backend.spawn(config)

    msg = TeammateMessage(text="work on it", from_agent="leader")
    await backend.send_message("rcvr@myteam", msg)

    entry = backend._active["rcvr@myteam"]
    got = await asyncio.wait_for(entry.hot_queue.get(), timeout=2.0)
    assert got.text == "work on it"

    await backend.shutdown("rcvr@myteam", force=True)


async def test_send_message_bare_agent_id_normalizes_to_default_team(backend, tmp_path, monkeypatch):
    """Debugger synthetic agents use ids like ``main`` without ``@team``."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    msg = TeammateMessage(text="ping", from_agent="debugger")
    await backend.send_message("main", msg)

    from openharness.swarm.mailbox import TeammateMailbox

    mailbox = TeammateMailbox(team_name="default", agent_id="main")
    messages = await mailbox.read_all(unread_only=False)
    assert any(m.payload.get("content") == "ping" for m in messages)


async def test_send_message_empty_agent_id_raises(backend):
    with pytest.raises(ValueError, match="non-empty"):
        await backend.send_message("", TeammateMessage(text="hi", from_agent="l"))


# ---------------------------------------------------------------------------
# active_agents / shutdown_all
# ---------------------------------------------------------------------------


async def test_active_agents_lists_running(backend, spawn_config):
    await backend.spawn(spawn_config)
    active = backend.active_agents()
    assert "worker@test-team" in active


async def test_shutdown_all(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in ("a", "b"):
        cfg = TeammateSpawnConfig(
            name=name,
            team="t",
            prompt="run",
            cwd="/tmp",
            parent_session_id="s",
        )
        await backend.spawn(cfg)

    await backend.shutdown_all(force=True, timeout=2.0)
    assert backend.active_agents() == []


async def test_start_in_process_teammate_emits_lifecycle_events(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("OPENHARNESS_TEAMMATE_USE_STUB", "1")
    store = get_event_store()
    store.clear()
    config = TeammateSpawnConfig(
        name="worker",
        team="demo",
        prompt="do work",
        cwd="/tmp",
        parent_session_id="root-session",
        parent_agent_id="leader@demo",
        root_agent_id="leader@demo",
        session_id="worker-session",
        lineage_path=["leader@demo"],
    )

    await start_in_process_teammate(
        config=config,
        agent_id="worker@demo",
        abort_controller=TeammateAbortController(),
        query_context=None,
    )

    events = store.events_for_agent("worker@demo")
    assert [event.event_type for event in events] == [
        "agent_spawned",
        "agent_became_running",
        "agent_finished",
    ]
