"""SQLAlchemy ORM models for PostgreSQL.

Migrated from PoC metronix/postgres/models.py.
Models: Workspace, User, WorkspaceMember, Connection, Config.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class WorkspaceRow(Base):  # type: ignore[misc]
    """Workspace for project/tenant isolation."""

    __tablename__ = "workspaces"

    id = Column(String(64), primary_key=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=True)
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by = Column(String(64), nullable=True)
    llm_telemetry_opt_out = Column(Boolean, nullable=False, server_default=text("false"))

    members = relationship(
        "WorkspaceMemberRow", back_populates="workspace", cascade="all, delete-orphan"
    )
    connections = relationship(
        "ConnectionRow", back_populates="workspace", cascade="all, delete-orphan"
    )
    configs = relationship("ConfigRow", back_populates="workspace", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_workspaces_slug", "slug"),
        Index("ix_workspaces_is_default", "is_default"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
        }


class UserRow(Base):  # type: ignore[misc]
    """User account."""

    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(100), nullable=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(20), default="user", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login_at = Column(DateTime, nullable=True)

    memberships = relationship(
        "WorkspaceMemberRow", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_is_active", "is_active"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class WorkspaceMemberRow(Base):  # type: ignore[misc]
    """User membership in a workspace with role."""

    __tablename__ = "workspace_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), default="member", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workspace = relationship("WorkspaceRow", back_populates="members")
    user = relationship("UserRow", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
        Index("ix_workspace_members_user", "user_id"),
    )


class ConnectionRow(Base):  # type: ignore[misc]
    """External integration connection (Jira, Confluence, etc.)."""

    __tablename__ = "connections"

    id = Column(String(64), primary_key=True)
    workspace_id = Column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    connector_type = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    config_encrypted = Column(LargeBinary, nullable=False)
    status = Column(String(32), nullable=False, server_default="active")
    enabled = Column(Boolean, server_default="true")
    error_message = Column(Text, nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    workspace = relationship("WorkspaceRow", back_populates="connections")

    __table_args__ = (
        Index("ix_connections_workspace", "workspace_id"),
        Index("ix_connections_type", "connector_type"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "connector_type": self.connector_type,
            "name": self.name,
            "status": self.status,
            "enabled": self.enabled,
            "error_message": self.error_message,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConfigRow(Base):  # type: ignore[misc]
    """Key-value configuration per workspace."""

    __tablename__ = "configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    key = Column(String(100), nullable=False)
    value = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    workspace = relationship("WorkspaceRow", back_populates="configs")

    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_workspace_config_key"),
        Index("ix_configs_workspace", "workspace_id"),
    )


class UserPlatformMappingRow(Base):  # type: ignore[misc]
    """Maps channel platform identities to internal users."""

    __tablename__ = "user_platform_mappings"

    channel = Column(Text, nullable=False, primary_key=True)
    channel_user_id = Column(Text, nullable=False, primary_key=True)
    workspace_id = Column(Text, nullable=False, primary_key=True)
    user_id = Column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "channel",
            "channel_user_id",
            "workspace_id",
            name="uq_user_platform_mapping",
        ),
        Index("ix_upm_user_id", "user_id"),
    )


class SyncLogRow(Base):  # type: ignore[misc]
    """Sync log entry for connector synchronization runs."""

    __tablename__ = "sync_logs"

    id = Column(String(64), primary_key=True)
    workspace_id = Column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    connection_id = Column(
        String(64), ForeignKey("connections.id", ondelete="CASCADE"), nullable=True
    )
    connector_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    documents_fetched = Column(Integer, nullable=False, server_default="0")
    documents_new = Column(Integer, nullable=False, server_default="0")
    documents_updated = Column(Integer, nullable=False, server_default="0")
    documents_skipped = Column(Integer, nullable=False, server_default="0")
    errors = Column(JSONB, nullable=False, server_default="[]")
    duration_ms = Column(Float, nullable=False, server_default="0")
    source_title = Column(String(255), nullable=True)
    qdrant_chunks = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_sync_logs_workspace", "workspace_id"),
        Index("ix_sync_logs_connection", "connection_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "connection_id": self.connection_id,
            "connector_type": self.connector_type,
            "status": self.status,
            "documents_fetched": self.documents_fetched,
            "documents_new": self.documents_new,
            "documents_updated": self.documents_updated,
            "documents_skipped": self.documents_skipped,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "source_title": self.source_title,
            "qdrant_chunks": self.qdrant_chunks,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class QueryTraceRow(Base):  # type: ignore[misc]
    """Query trace entry for RAG query execution tracking."""

    __tablename__ = "query_traces"

    id = Column(String(64), primary_key=True)
    workspace_id = Column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    query = Column(Text, nullable=False)
    trace = Column(JSONB, nullable=False)
    total_ms = Column(Float, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_query_traces_workspace", "workspace_id"),
        Index("ix_query_traces_created", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "query": self.query,
            "trace": self.trace,
            "total_ms": self.total_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RagDebugTraceRow(Base):  # type: ignore[misc]
    """Full RAG pipeline debug trace (one row per traced chat request).

    ``trace_id`` is the request ``correlation_id``. Self-contained: ``trace``
    JSONB holds the whole phased structure (input → preprocessing → recall →
    scoring → rerank → context → generation). Independent of ``llm_generation_log``.
    Not a FK to workspaces so rows survive workspace deletion.
    """

    __tablename__ = "rag_debug_traces"

    trace_id = Column(UUID(as_uuid=False), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    workspace_id = Column(Text, nullable=True)
    user_id = Column(Text, nullable=True)
    agent_id = Column(Text, nullable=True)
    source = Column(Text, nullable=True)
    query = Column(Text, nullable=False)
    total_ms = Column(Float, nullable=False, server_default="0")
    trace = Column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_rag_debug_traces_ws_created", "workspace_id", text("created_at DESC")),
    )


class DocumentFetchStatsRow(Base):  # type: ignore[misc]
    """Per-day document fetch statistics for FinOps cost savings."""

    __tablename__ = "document_fetch_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    doc_label = Column(String(512), nullable=False)
    title = Column(String(1024), nullable=False, server_default="")
    fetch_count = Column(Integer, nullable=False, server_default="0")
    total_context_words = Column(Integer, nullable=False, server_default="0")
    fetch_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("workspace_id", "doc_label", "fetch_date", name="uq_doc_fetch_stats"),
        Index("ix_doc_fetch_stats_workspace", "workspace_id"),
        Index("ix_doc_fetch_stats_date", "workspace_id", "fetch_date"),
    )


class LLMGenerationLogRow(Base):  # type: ignore[misc]
    """ORM model for llm_generation_log (MTRNIX-336).

    Used for inserts only — the export script queries via raw SQL.
    Note: workspace_id is NOT a FK to workspaces so rows are still written
    when workspace_id is NULL or when the workspace was deleted.
    """

    __tablename__ = "llm_generation_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # -- what kind of call --
    call_site = Column(Text, nullable=False)
    source = Column(Text, nullable=True)

    # -- request context (from ContextVar; may be NULL) --
    workspace_id = Column(Text, nullable=True)
    user_id = Column(Text, nullable=True)
    agent_id = Column(Text, nullable=True)
    correlation_id = Column(UUID(as_uuid=False), nullable=True)

    # -- model + provider --
    provider = Column(Text, nullable=False)
    model = Column(Text, nullable=False)

    # -- the exchange --
    request_messages = Column(JSONB, nullable=False)
    response_content = Column(Text, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    # -- outcome --
    success = Column(Boolean, nullable=False)
    error_class = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    # -- call-site-specific extras --
    # NOTE: 'metadata' is reserved by SQLAlchemy Declarative API, so the
    # Python attribute is named 'extra_metadata' while the DB column stays 'metadata'.
    extra_metadata = Column("metadata", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_llm_log_ws_created", "workspace_id", text("created_at DESC")),
        Index("ix_llm_log_call_site_created", "call_site", text("created_at DESC")),
        Index(
            "ix_llm_log_correlation",
            "correlation_id",
            postgresql_where=text("correlation_id IS NOT NULL"),
        ),
    )
