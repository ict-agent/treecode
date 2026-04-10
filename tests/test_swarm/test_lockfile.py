"""Tests for swarm file-lock helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from treecode.swarm.lockfile import SwarmLockUnavailableError, exclusive_file_lock


def test_exclusive_file_lock_creates_lock_file_on_posix(tmp_path: Path):
    lock_path = tmp_path / "locks" / "mailbox.lock"

    with exclusive_file_lock(lock_path, platform_name="linux"):
        assert lock_path.exists()

    assert lock_path.exists()


def test_exclusive_file_lock_routes_windows_branch(monkeypatch, tmp_path: Path):
    calls: list[Path] = []

    @contextmanager
    def _fake_windows_lock(lock_path: Path):
        calls.append(lock_path)
        yield

    monkeypatch.setattr("treecode.swarm.lockfile._exclusive_windows_lock", _fake_windows_lock)

    lock_path = tmp_path / "windows.lock"
    with exclusive_file_lock(lock_path, platform_name="windows"):
        pass

    assert calls == [lock_path]


def test_exclusive_file_lock_rejects_unknown_platform(tmp_path: Path):
    with pytest.raises(SwarmLockUnavailableError, match="not supported"):
        with exclusive_file_lock(tmp_path / "unknown.lock", platform_name="unknown"):
            pass
