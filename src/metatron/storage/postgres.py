"""PostgreSQL async store — CRUD for all tables.

Uses asyncpg via SQLAlchemy async engine. All operations are
workspace-scoped where applicable. No ORM models — we use
raw SQL with parameterized queries for clarity and control.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from metatron.core.models import (
    Connection,
    FileRecord,
    Skill,
    User,
    Workspace,
)

logger = structlog.get_logger()


class PostgresStore:
    """Async PostgreSQL data store for metadata, skills, auth, and traces.

    All methods accept explicit parameters — no global state.
    Connection pooling is managed by SQLAlchemy's async engine.
    """

    def __init__(self, dsn: str, pool_size: int = 10) -> None:
        self._engine: AsyncEngine = create_async_engine(
            dsn,
            pool_size=pool_size,
            pool_pre_ping=True,
        )

    # --- Workspaces ---

    async def create_workspace(self, workspace: Workspace) -> Workspace:
        """Insert a new workspace.

        Args:
            workspace: Workspace to create (id, name, slug).

        Returns:
            The created workspace.
        """
        logger.info("postgres.workspace.create", workspace_id=workspace.id)
        # TODO: implement workspace creation
        # 1. INSERT INTO workspaces (id, name, slug, created_at) VALUES (...)
        # 2. Return workspace
        raise NotImplementedError("Workspace creation not yet implemented")

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        """Fetch a workspace by ID.

        Args:
            workspace_id: The workspace ID.

        Returns:
            Workspace if found, None otherwise.
        """
        logger.info("postgres.workspace.get", workspace_id=workspace_id)
        # TODO: implement
        # SELECT * FROM workspaces WHERE id = $1
        raise NotImplementedError("Workspace fetch not yet implemented")

    # --- Users ---

    async def create_user(self, user: User) -> User:
        """Insert a new user."""
        logger.info("postgres.user.create", user_id=user.id)
        # TODO: implement
        raise NotImplementedError("User creation not yet implemented")

    async def get_user(self, user_id: str) -> User | None:
        """Fetch a user by ID."""
        logger.info("postgres.user.get", user_id=user_id)
        # TODO: implement
        raise NotImplementedError("User fetch not yet implemented")

    async def get_user_by_email(self, email: str) -> User | None:
        """Fetch a user by email."""
        logger.info("postgres.user.get_by_email", email=email)
        # TODO: implement
        raise NotImplementedError("User fetch by email not yet implemented")

    # --- Skills ---

    async def list_skills(
        self, workspace_id: str | None = None, enabled_only: bool = True
    ) -> list[Skill]:
        """List skills, optionally filtered by workspace and enabled status.

        Args:
            workspace_id: If set, include workspace-specific + global skills.
            enabled_only: If True, exclude disabled skills.

        Returns:
            List of Skill objects.
        """
        logger.info("postgres.skills.list", workspace_id=workspace_id)
        # TODO: implement
        # SELECT * FROM skills WHERE (workspace_id = $1 OR workspace_id IS NULL)
        # AND ($2 OR enabled = true) ORDER BY name
        raise NotImplementedError("Skill listing not yet implemented")

    async def upsert_skill(self, skill: Skill) -> Skill:
        """Insert or update a skill (by name + workspace_id).

        Used by builtin skill loader and CRUD API.
        """
        logger.info("postgres.skill.upsert", skill_name=skill.name)
        # TODO: implement
        # INSERT INTO skills (...) VALUES (...) ON CONFLICT (name, workspace_id)
        # DO UPDATE SET ...
        raise NotImplementedError("Skill upsert not yet implemented")

    # --- Connections ---

    async def create_connection(self, connection: Connection) -> Connection:
        """Insert a new connector configuration."""
        logger.info("postgres.connection.create", connector_type=connection.connector_type)
        # TODO: implement
        raise NotImplementedError("Connection creation not yet implemented")

    async def list_connections(self, workspace_id: str) -> list[Connection]:
        """List all connections for a workspace."""
        logger.info("postgres.connections.list", workspace_id=workspace_id)
        # TODO: implement
        raise NotImplementedError("Connection listing not yet implemented")

    async def update_connection_status(
        self, connection_id: str, status: str, last_synced_at: datetime | None = None
    ) -> None:
        """Update connection status and optional sync timestamp."""
        logger.info("postgres.connection.update_status", connection_id=connection_id)
        # TODO: implement
        raise NotImplementedError("Connection status update not yet implemented")

    # --- Files ---

    async def create_file_record(self, record: FileRecord) -> FileRecord:
        """Insert a file metadata record."""
        logger.info("postgres.file.create", file_id=record.id)
        # TODO: implement
        raise NotImplementedError("File record creation not yet implemented")

    async def get_file_record(self, file_id: str) -> FileRecord | None:
        """Fetch a file record by ID."""
        logger.info("postgres.file.get", file_id=file_id)
        # TODO: implement
        raise NotImplementedError("File record fetch not yet implemented")

    async def list_file_records(self, workspace_id: str) -> list[FileRecord]:
        """List all files for a workspace."""
        logger.info("postgres.files.list", workspace_id=workspace_id)
        # TODO: implement
        raise NotImplementedError("File listing not yet implemented")

    # --- Observability ---

    async def store_query_trace(
        self, workspace_id: str, trace_data: dict[str, object]
    ) -> str:
        """Store a query trace (JSONB) and return its ID.

        Args:
            workspace_id: Workspace this query belongs to.
            trace_data: Full trace dict from QueryTrace.to_dict().

        Returns:
            ID of the stored trace.
        """
        logger.info("postgres.trace.store", workspace_id=workspace_id)
        # TODO: implement
        # INSERT INTO query_traces (id, workspace_id, trace, created_at)
        raise NotImplementedError("Trace storage not yet implemented")

    async def store_sync_log(
        self, workspace_id: str, connection_id: str, log_data: dict[str, object]
    ) -> None:
        """Store a sync run log entry."""
        logger.info("postgres.sync_log.store", workspace_id=workspace_id)
        # TODO: implement
        raise NotImplementedError("Sync log storage not yet implemented")

    async def close(self) -> None:
        """Dispose of the engine and its connection pool."""
        await self._engine.dispose()
