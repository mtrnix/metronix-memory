"""SQLAlchemy ORM models for PostgreSQL.

Migrated from PoC metatron/postgres/models.py.
Models: Workspace, User, WorkspaceMember, Connection, Config.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import JSONB
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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(64), nullable=True)

    members = relationship("WorkspaceMemberRow", back_populates="workspace", cascade="all, delete-orphan")
    connections = relationship("ConnectionRow", back_populates="workspace", cascade="all, delete-orphan")
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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    memberships = relationship("WorkspaceMemberRow", back_populates="user", cascade="all, delete-orphan")

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
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
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
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    connector_type = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    config_encrypted = Column(LargeBinary, nullable=False)
    status = Column(String(32), nullable=False, server_default="active")
    enabled = Column(Boolean, server_default="true")
    error_message = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

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
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

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
            "channel", "channel_user_id", "workspace_id",
            name="uq_user_platform_mapping",
        ),
        Index("ix_upm_user_id", "user_id"),
    )


class SyncLogRow(Base):  # type: ignore[misc]
    """Sync log entry for connector synchronization runs."""

    __tablename__ = "sync_logs"

    id = Column(String(64), primary_key=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    connection_id = Column(String(64), ForeignKey("connections.id", ondelete="CASCADE"), nullable=True)
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
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
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


class DocumentFetchStatsRow(Base):  # type: ignore[misc]
    """Per-day document fetch statistics for FinOps cost savings."""

    __tablename__ = "document_fetch_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
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
