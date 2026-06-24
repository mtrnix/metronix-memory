from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ExportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class ExportScope:
    all_workspaces: bool = False
    workspace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"all_workspaces": self.all_workspaces, "workspace_id": self.workspace_id}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExportScope:
        return cls(
            all_workspaces=bool(d.get("all_workspaces", False)),
            workspace_id=d.get("workspace_id"),
        )

    def key(self) -> str:
        return "all" if self.all_workspaces else f"ws:{self.workspace_id}"


@dataclass
class ExportJob:
    id: str
    scope: ExportScope
    status: ExportStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    workspace_count: int = 0
    agent_count: int = 0
    memory_record_count: int = 0
    document_count: int = 0
    size_bytes: int = 0
    archive_path: str | None = None
    download_token: str | None = None
    error: str | None = None
