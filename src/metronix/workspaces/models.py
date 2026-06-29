"""Data models for workspace management.

Migrated from PoC metronix/workspaces/models.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class WorkspaceStats:
    """Statistics for a workspace."""

    document_count: int = 0
    entity_count: int = 0
    jira_issue_count: int = 0
    last_upload_time: str | None = None
    total_chunks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceStats:
        return cls(**data)


@dataclass
class Workspace:
    """Workspace model for data isolation."""

    workspace_id: str
    name: str
    description: str | None = None
    created_at: str | None = None
    user_id: str = "user"
    is_active: bool = True
    config: dict[str, Any] | None = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now(UTC).isoformat()
        if self.config is None:
            self.config = {}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Workspace:
        return cls(**data)

    def get_qdrant_collection_name(self) -> str:
        return f"mem_docs_hybrid_{self.workspace_id}"

    def is_default(self) -> bool:
        from metronix.core.config import Settings

        settings = Settings()
        return self.workspace_id == settings.default_workspace_id
