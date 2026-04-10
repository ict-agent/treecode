"""Run-scoped archive storage for multi-agent debugger sessions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
import re
from uuid import uuid4

from treecode.config.paths import get_data_dir
from treecode.swarm.events import SwarmEvent


@dataclass(frozen=True)
class RunArchiveRecord:
    """Metadata for one archived multi-agent run."""

    run_id: str
    label: str
    created_at: float
    snapshot_path: str
    events_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "label": self.label,
            "created_at": self.created_at,
            "snapshot_path": self.snapshot_path,
            "events_path": self.events_path,
        }


class RunArchiveStore:
    """Persist and compare archived debugger runs."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or (get_data_dir() / "swarm" / "archives")
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def archive_run(
        self,
        *,
        label: str,
        snapshot: dict[str, object],
        events: tuple[SwarmEvent, ...],
    ) -> RunArchiveRecord:
        run_id = f"run-{uuid4().hex[:10]}"
        run_dir = self._storage_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = run_dir / "snapshot.json"
        events_path = run_dir / "events.jsonl"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        events_path.write_text(
            "\n".join(json.dumps(event.to_dict()) for event in events) + ("\n" if events else ""),
            encoding="utf-8",
        )
        record = RunArchiveRecord(
            run_id=run_id,
            label=label,
            created_at=time.time(),
            snapshot_path=str(snapshot_path),
            events_path=str(events_path),
        )
        (run_dir / "record.json").write_text(json.dumps(record.to_dict()), encoding="utf-8")
        return record

    def list_archives(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for path in sorted(self._storage_dir.glob("*/record.json")):
            records.append(json.loads(path.read_text(encoding="utf-8")))
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def load_snapshot(self, run_id: str) -> dict[str, object]:
        validated_run_id = self._validate_run_id(run_id)
        return json.loads((self._storage_dir / validated_run_id / "snapshot.json").read_text(encoding="utf-8"))

    def compare_runs(self, left_run_id: str, right_run_id: str) -> dict[str, object]:
        left = self.load_snapshot(left_run_id)
        right = self.load_snapshot(right_run_id)
        differences: dict[str, dict[str, object]] = {}
        for key in ("agent_count", "message_count", "event_count", "pending_approvals", "max_depth"):
            left_value = left.get("overview", {}).get(key)
            right_value = right.get("overview", {}).get(key)
            if left_value != right_value:
                differences[key] = {"left": left_value, "right": right_value}
        left_name = left.get("scenario_view", {}).get("scenario_name")
        right_name = right.get("scenario_view", {}).get("scenario_name")
        if left_name != right_name:
            differences["scenario_name"] = {
                "left": left_name,
                "right": right_name,
            }
        return {
            "left_run_id": left_run_id,
            "right_run_id": right_run_id,
            "differences": differences,
        }

    @staticmethod
    def _validate_run_id(run_id: str) -> str:
        if not re.fullmatch(r"run-[0-9a-f]{10}", run_id):
            raise ValueError(f"Invalid run_id: {run_id}")
        return run_id
