"""PostgreSQL async store — CRUD for all tables.

Uses asyncpg via SQLAlchemy async engine. All operations are
workspace-scoped where applicable. No ORM models — we use
raw SQL with parameterized queries for clarity and control.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from metatron.core.models import (
    Connection,
    DocumentVersion,
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
        self, workspace_id: str, query: str, trace: dict[str, Any], total_ms: float
    ) -> str:
        """Store a query trace and return its ID.

        Args:
            workspace_id: Workspace this query belongs to.
            query: The user query text.
            trace: Trace data (timing, results, etc.) as dict.
            total_ms: Total query execution time in milliseconds.

        Returns:
            ID of the stored trace.
        """
        import json
        
        logger.info("postgres.trace.store", workspace_id=workspace_id)
        
        trace_id = uuid4().hex
        now = datetime.now(UTC)
        
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO query_traces
                    (id, workspace_id, query, trace, total_ms, created_at)
                    VALUES (:id, :workspace_id, :query, :trace::jsonb, :total_ms, :created_at)
                """),
                {
                    "id": trace_id,
                    "workspace_id": workspace_id,
                    "query": query,
                    "trace": json.dumps(trace),  # Explicit serialization for raw SQL
                    "total_ms": total_ms,
                    "created_at": now,
                },
            )
        
        return trace_id

    async def store_sync_log(
        self, workspace_id: str, connection_id: str, log_data: dict[str, object]
    ) -> None:
        """Store a sync run log entry."""
        logger.info("postgres.sync_log.store", workspace_id=workspace_id)
        # TODO: implement
        raise NotImplementedError("Sync log storage not yet implemented")

    # --- Document Versioning ---

    @staticmethod
    def _row_to_version(row: Any) -> DocumentVersion:
        """Convert a DB row to DocumentVersion using named column access."""
        m = row._mapping
        created = m["created_at"]
        if created and not created.tzinfo:
            created = created.replace(tzinfo=UTC)
        # JSONB columns return dicts directly — no json.loads needed
        fields = m["changed_fields"] if m["changed_fields"] else {}
        return DocumentVersion(
            id=m["id"],
            document_id=m["document_id"],
            version_number=m["version_number"],
            content=m["content"],
            content_hash=m["content_hash"],
            created_at=created or datetime.now(UTC),
            changed_fields=fields,
            sync_source=m["sync_source"],
        )

    async def store_document_version(
        self,
        document_id: str,
        content: str,
        changed_fields: dict[str, list[str]] | None = None,
        sync_source: str = "manual",
    ) -> DocumentVersion:
        """Store a new version of a document.

        Args:
            document_id: Reference to parent document.
            content: Document content at this version.
            changed_fields: Fields that changed, e.g., {'title': ['old', 'new']}.
            sync_source: Source of change (confluence, jira, notion, manual).

        Returns:
            The created DocumentVersion.
        """
        logger.info(
            "postgres.document_version.store",
            document_id=document_id,
            sync_source=sync_source,
        )

        content_hash = hashlib.sha256(content.encode()).hexdigest()

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT COALESCE(MAX(version_number), 0) as max_version
                    FROM document_versions
                    WHERE document_id = :doc_id
                """),
                {"doc_id": document_id},
            )
            max_version = result.scalar() or 0
            version_number = max_version + 1

            now = datetime.now(UTC)
            version_id = uuid4().hex

            # Pass dict directly — asyncpg serialises it for the JSONB column
            await conn.execute(
                text("""
                    INSERT INTO document_versions
                    (id, document_id, version_number, content, content_hash,
                     created_at, changed_fields, sync_source)
                    VALUES (:id, :doc_id, :version_num, :content, :hash,
                            :created, :fields, :source)
                """),
                {
                    "id": version_id,
                    "doc_id": document_id,
                    "version_num": version_number,
                    "content": content,
                    "hash": content_hash,
                    "created": now,
                    "fields": json.dumps(changed_fields or {}),
                    "source": sync_source,
                },
            )

            return DocumentVersion(
                id=version_id,
                document_id=document_id,
                version_number=version_number,
                content=content,
                content_hash=content_hash,
                created_at=now,
                changed_fields=changed_fields or {},
                sync_source=sync_source,
            )

    async def get_document_history(
        self,
        document_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[DocumentVersion], int]:
        """Get version history for a document (newest first).

        Args:
            document_id: Document to fetch history for.
            limit: Max versions to return.
            offset: Pagination offset.

        Returns:
            Tuple of (versions list, total count).
        """
        logger.info(
            "postgres.document_history.get",
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

        async with self._engine.begin() as conn:
            count_result = await conn.execute(
                text("""
                    SELECT COUNT(*) FROM document_versions
                    WHERE document_id = :doc_id
                """),
                {"doc_id": document_id},
            )
            total = count_result.scalar() or 0

            result = await conn.execute(
                text("""
                    SELECT id, document_id, version_number, content, content_hash,
                           created_at, changed_fields, sync_source
                    FROM document_versions
                    WHERE document_id = :doc_id
                    ORDER BY version_number DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"doc_id": document_id, "limit": limit, "offset": offset},
            )

            versions = [self._row_to_version(row) for row in result]

            return versions, total

    async def get_latest_version(self, document_id: str) -> DocumentVersion | None:
        """Get the latest version of a document.

        Args:
            document_id: Document to fetch latest version for.

        Returns:
            Latest DocumentVersion or None if no versions exist.
        """
        logger.info("postgres.latest_version.get", document_id=document_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, document_id, version_number, content, content_hash,
                           created_at, changed_fields, sync_source
                    FROM document_versions
                    WHERE document_id = :doc_id
                    ORDER BY version_number DESC
                    LIMIT 1
                """),
                {"doc_id": document_id},
            )

            row = result.first()
            if not row:
                return None

            return self._row_to_version(row)

    async def close(self) -> None:
        """Dispose of the engine and its connection pool."""
        await self._engine.dispose()
