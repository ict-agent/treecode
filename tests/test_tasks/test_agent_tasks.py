"""Tests for delegated agent task helpers (``/agents`` scope)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openharness.config.paths import get_tasks_dir
from openharness.tasks.agent_tasks import (
    AGENT_TASK_LIST_CAP,
    count_agent_tasks_for_cwd,
    list_agent_tasks_for_cwd,
)
from openharness.tasks.manager import BackgroundTaskManager
from openharness.tasks.types import TaskRecord


@pytest.mark.asyncio
async def test_list_and_count_agent_tasks_respects_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    a = tmp_path / "pa"
    b = tmp_path / "pb"
    a.mkdir()
    b.mkdir()

    ma = BackgroundTaskManager()
    await ma.create_agent_task(
        prompt="p",
        description="in-a",
        cwd=a,
        command="python -u -c \"import sys; print(sys.stdin.readline())\"",
    )
    mb = BackgroundTaskManager()
    await mb.create_agent_task(
        prompt="q",
        description="in-b",
        cwd=b,
        command="python -u -c \"import sys; print(sys.stdin.readline())\"",
    )

    listed = list_agent_tasks_for_cwd(cwd=a, running_only=True)
    assert len(listed) == 1
    assert listed[0].description == "in-a"
    assert count_agent_tasks_for_cwd(cwd=a) == 1
    assert count_agent_tasks_for_cwd(cwd=b) == 1


def test_agent_task_list_cap_constant_matches_agents_command_docs():
    assert AGENT_TASK_LIST_CAP == 80


def test_running_only_agent_task_queries_ignore_dead_pid_records(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    cwd = tmp_path / "proj"
    cwd.mkdir()
    tasks_dir = get_tasks_dir()
    tasks_dir.mkdir(parents=True, exist_ok=True)

    ghost = TaskRecord(
        id="aghost000",
        type="local_agent",
        status="running",
        description="ghost",
        cwd=str(cwd.resolve()),
        output_file=tasks_dir / "aghost000.log",
        metadata={"pid": str(2**30)},
        created_at=0.0,
    )
    ghost.output_file.write_text("", encoding="utf-8")
    (tasks_dir / "aghost000.json").write_text(json.dumps(ghost.to_dict()), encoding="utf-8")

    alive = TaskRecord(
        id="aalive000",
        type="local_agent",
        status="running",
        description="alive",
        cwd=str(cwd.resolve()),
        output_file=tasks_dir / "aalive000.log",
        metadata={"pid": str(os.getpid())},
        created_at=1.0,
    )
    alive.output_file.write_text("", encoding="utf-8")
    (tasks_dir / "aalive000.json").write_text(json.dumps(alive.to_dict()), encoding="utf-8")

    listed = list_agent_tasks_for_cwd(cwd=cwd, running_only=True)
    assert [task.id for task in listed] == ["aalive000"]
    assert count_agent_tasks_for_cwd(cwd=cwd, running_only=True) == 1
