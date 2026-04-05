"""Task data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


TaskType = Literal["local_bash", "local_agent", "remote_agent", "in_process_teammate"]
TaskStatus = Literal["pending", "running", "completed", "failed", "killed"]


@dataclass
class TaskRecord:
    """Runtime representation of a background task."""

    id: str
    type: TaskType
    status: TaskStatus
    description: str
    cwd: str
    output_file: Path
    command: str | None = None
    prompt: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    ended_at: float | None = None
    return_code: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialize the task record for on-disk persistence."""
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "description": self.description,
            "cwd": self.cwd,
            "output_file": str(self.output_file),
            "command": self.command,
            "prompt": self.prompt,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "return_code": self.return_code,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TaskRecord":
        """Load a persisted task record."""
        started_at = data.get("started_at")
        ended_at = data.get("ended_at")
        return_code = data.get("return_code")
        return cls(
            id=str(data["id"]),
            type=data["type"],  # type: ignore[arg-type]
            status=data["status"],  # type: ignore[arg-type]
            description=str(data["description"]),
            cwd=str(data["cwd"]),
            output_file=Path(str(data["output_file"])),
            command=data.get("command") and str(data["command"]) or None,
            prompt=data.get("prompt") and str(data["prompt"]) or None,
            created_at=float(data.get("created_at", 0.0)),
            started_at=float(started_at) if started_at is not None else None,
            ended_at=float(ended_at) if ended_at is not None else None,
            return_code=int(return_code) if return_code is not None else None,
            metadata={str(key): str(value) for key, value in dict(data.get("metadata", {})).items()},
        )
