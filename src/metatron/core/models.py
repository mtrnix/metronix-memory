"""Pure data models — no ORM, no Pydantic models, no business logic.

These dataclasses define the shapes that flow between layers.
Every layer speaks the same language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class ChunkType(StrEnum):
    """Chunk role within a document (OpenMemory root-child pattern)."""

    ROOT = "root"
    CHILD = "child"
    STANDALONE = "standalone"


class Role(StrEnum):
    """Authorization roles — ordered by privilege."""

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


class ConnectionStatus(StrEnum):
    """Lifecycle of a data-source connection."""

    ACTIVE = "active"
    SYNCING = "syncing"
    ERROR = "error"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Documents & chunks
# ---------------------------------------------------------------------------


@dataclass
class Document:
    """A document fetched from a connector, before chunking."""

    id: str = field(default_factory=lambda: uuid4().hex)
    workspace_id: str = ""
    source_type: str = ""          # e.g. "confluence", "jira", "github"
    source_id: str = ""            # connector-specific unique ID
    title: str = ""
    content: str = ""
    url: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    source_role: str = ""              # e.g. "knowledge_base", "task_tracker", "communication", "user_upload"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Chunk:
    """A piece of a document ready for embedding + vector storage."""

    id: str = field(default_factory=lambda: uuid4().hex)
    document_id: str = ""
    workspace_id: str = ""
    chunk_type: ChunkType = ChunkType.STANDALONE
    parent_id: str | None = None   # points to ROOT chunk if this is CHILD
    content: str = ""
    token_count: int = 0
    simhash: int = 0
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class DocumentVersion:
    """Represents a specific version of a document for temporal tracking."""

    id: str = field(default_factory=lambda: uuid4().hex)
    document_id: str = ""
    version_number: int = 1
    content: str = ""
    content_hash: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    changed_fields: dict[str, list[str]] = field(default_factory=dict)
    sync_source: str = "manual"


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------


@dataclass
class IncomingMessage:
    """A message received from a channel (Telegram, Slack, etc.)."""

    channel: str = ""              # "telegram", "slack"
    channel_user_id: str = ""      # platform-specific user ID
    workspace_id: str = ""
    text: str = ""
    thread_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """A response to be sent back through a channel."""

    text: str = ""
    channel: str = ""
    channel_user_id: str = ""
    thread_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Skills & connections
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    """A skill definition stored in PostgreSQL.

    Skills are Markdown documents that teach the LLM how to use a tool.
    Builtins ship as .md files and get loaded on first migration.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""
    description: str = ""
    content: str = ""              # full Markdown body
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    enabled: bool = True
    builtin: bool = False
    workspace_id: str | None = None  # None = global


@dataclass
class Connection:
    """A configured data-source connection for a workspace."""

    id: str = field(default_factory=lambda: uuid4().hex)
    workspace_id: str = ""
    connector_type: str = ""       # "confluence", "jira", etc.
    name: str = ""                 # User-friendly label
    config_encrypted: bytes = b""  # Fernet-encrypted JSON
    status: ConnectionStatus = ConnectionStatus.ACTIVE
    enabled: bool = True
    error_message: str | None = None
    last_synced_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


@dataclass
class FileRecord:
    """Metadata for an uploaded file stored on disk."""

    id: str = field(default_factory=lambda: uuid4().hex)
    workspace_id: str = ""
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    storage_path: str = ""
    uploaded_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@dataclass
class User:
    """An internal user, mapped from platform identities."""

    id: str = field(default_factory=lambda: uuid4().hex)
    username: str = ""
    email: str = ""
    role: Role = Role.VIEWER
    workspace_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Workspace:
    """An isolated tenant — separate Qdrant collection, separate data."""

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""
    slug: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Sync & observability
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """Outcome of a connector sync run."""

    connector_type: str = ""
    workspace_id: str = ""
    documents_fetched: int = 0
    documents_new: int = 0
    documents_updated: int = 0
    documents_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class QueryStep:
    """A single step in a 7-step query trace (for benchmarker API)."""

    name: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, str | int | float] = field(default_factory=dict)
