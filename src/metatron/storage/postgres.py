"""PostgreSQL async store — CRUD for all tables.

Uses asyncpg via SQLAlchemy async engine. All operations are
workspace-scoped where applicable. No ORM models — we use
raw SQL with parameterized queries for clarity and control.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from metatron.core.models import (
    DocumentVersion,
    FileRecord,
    RawDocument,
    Skill,
    User,
    Workspace,
)

logger = structlog.get_logger()


def _to_pg_bigint(h: int) -> int:
    """Convert unsigned 64-bit hash to signed PG BIGINT range."""
    return h if h < (1 << 63) else h - (1 << 64)


def _from_pg_bigint(v: int) -> int:
    """Convert signed PG BIGINT back to unsigned 64-bit hash."""
    return v if v >= 0 else v + (1 << 64)


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

    async def create_connection(
        self,
        workspace_id: str,
        connector_type: str,
        name: str,
        config: dict,
        fernet_key: str,
    ) -> dict:
        """Insert a new connector configuration.

        Args:
            workspace_id: Workspace this connection belongs to.
            connector_type: Type of connector (confluence, jira, etc.).
            name: User-friendly label.
            config: Plaintext config dict (will be encrypted).
            fernet_key: Fernet key for encrypting config.

        Returns:
            Connection dict with masked secrets.
        """
        from metatron.connectors.schemas import mask_secrets, validate_config
        from metatron.storage.encryption import encrypt_value

        errors = validate_config(connector_type, config)
        if errors:
            raise ValueError("; ".join(errors))

        connection_id = uuid4().hex
        now = datetime.now(UTC)
        encrypted = encrypt_value(json.dumps(config), fernet_key)

        logger.info(
            "postgres.connection.create",
            connection_id=connection_id,
            connector_type=connector_type,
        )

        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO connections
                    (id, workspace_id, connector_type, name, config_encrypted,
                     status, enabled, created_at)
                    VALUES (:id, :workspace_id, :connector_type, :name,
                            :config_encrypted, 'active', true, :created_at)
                """),
                {
                    "id": connection_id,
                    "workspace_id": workspace_id,
                    "connector_type": connector_type,
                    "name": name,
                    "config_encrypted": encrypted,
                    "created_at": now,
                },
            )

        return {
            "id": connection_id,
            "workspace_id": workspace_id,
            "connector_type": connector_type,
            "name": name,
            "config": mask_secrets(connector_type, config),
            "status": "active",
            "enabled": True,
            "error_message": None,
            "last_synced_at": None,
            "created_at": now.isoformat(),
            "updated_at": None,
        }

    async def list_connections(self, workspace_id: str, fernet_key: str) -> list[dict]:
        """List all connections for a workspace with masked secrets.

        Args:
            workspace_id: Workspace to list connections for.
            fernet_key: Fernet key for decrypting config (to then mask).

        Returns:
            List of connection dicts with masked secret fields.
        """
        from metatron.connectors.schemas import mask_secrets
        from metatron.storage.encryption import decrypt_value

        logger.info("postgres.connections.list", workspace_id=workspace_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, workspace_id, connector_type, name,
                           config_encrypted, status, enabled, error_message,
                           last_synced_at, created_at, updated_at
                    FROM connections
                    WHERE workspace_id = :workspace_id
                    ORDER BY created_at DESC
                """),
                {"workspace_id": workspace_id},
            )
            rows = result.fetchall()

        connections = []
        for row in rows:
            m = row._mapping
            try:
                config = json.loads(decrypt_value(m["config_encrypted"], fernet_key))
            except Exception:
                config = {}
            connections.append(
                {
                    "id": m["id"],
                    "workspace_id": m["workspace_id"],
                    "connector_type": m["connector_type"],
                    "name": m["name"],
                    "config": mask_secrets(m["connector_type"], config),
                    "status": m["status"],
                    "enabled": m["enabled"],
                    "error_message": m["error_message"],
                    "last_synced_at": m["last_synced_at"].isoformat()
                    if m["last_synced_at"]
                    else None,
                    "created_at": m["created_at"].isoformat() if m["created_at"] else None,
                    "updated_at": m["updated_at"].isoformat() if m["updated_at"] else None,
                }
            )
        return connections

    async def get_connection(self, connection_id: str, fernet_key: str) -> dict | None:
        """Fetch a connection by ID with masked secrets.

        Args:
            connection_id: Connection ID.
            fernet_key: Fernet key for decrypting config (to then mask).

        Returns:
            Connection dict with masked secrets, or None.
        """
        from metatron.connectors.schemas import mask_secrets
        from metatron.storage.encryption import decrypt_value

        logger.info("postgres.connection.get", connection_id=connection_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, workspace_id, connector_type, name,
                           config_encrypted, status, enabled, error_message,
                           last_synced_at, created_at, updated_at
                    FROM connections
                    WHERE id = :id
                """),
                {"id": connection_id},
            )
            row = result.first()

        if not row:
            return None

        m = row._mapping
        try:
            config = json.loads(decrypt_value(m["config_encrypted"], fernet_key))
        except Exception:
            config = {}

        return {
            "id": m["id"],
            "workspace_id": m["workspace_id"],
            "connector_type": m["connector_type"],
            "name": m["name"],
            "config": mask_secrets(m["connector_type"], config),
            "status": m["status"],
            "enabled": m["enabled"],
            "error_message": m["error_message"],
            "last_synced_at": m["last_synced_at"].isoformat() if m["last_synced_at"] else None,
            "created_at": m["created_at"].isoformat() if m["created_at"] else None,
            "updated_at": m["updated_at"].isoformat() if m["updated_at"] else None,
        }

    async def get_connection_decrypted(self, connection_id: str, fernet_key: str) -> dict | None:
        """Fetch a connection by ID with full plaintext config.

        For internal use only (e.g., passing config to connector.configure()).

        Args:
            connection_id: Connection ID.
            fernet_key: Fernet key for decrypting config.

        Returns:
            Connection dict with plaintext config, or None.
        """
        from metatron.storage.encryption import decrypt_value

        logger.info("postgres.connection.get_decrypted", connection_id=connection_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, workspace_id, connector_type, name,
                           config_encrypted, status, enabled, error_message,
                           last_synced_at, created_at, updated_at
                    FROM connections
                    WHERE id = :id
                """),
                {"id": connection_id},
            )
            row = result.first()

        if not row:
            return None

        m = row._mapping
        config = json.loads(decrypt_value(m["config_encrypted"], fernet_key))

        return {
            "id": m["id"],
            "workspace_id": m["workspace_id"],
            "connector_type": m["connector_type"],
            "name": m["name"],
            "config": config,
            "status": m["status"],
            "enabled": m["enabled"],
            "error_message": m["error_message"],
            "last_synced_at": m["last_synced_at"].isoformat() if m["last_synced_at"] else None,
            "created_at": m["created_at"].isoformat() if m["created_at"] else None,
            "updated_at": m["updated_at"].isoformat() if m["updated_at"] else None,
        }

    async def update_connection(
        self, connection_id: str, updates: dict, fernet_key: str
    ) -> dict | None:
        """Update a connection's config and/or metadata.

        Handles secret merging: if a secret field is '***', the old value is preserved.

        Args:
            connection_id: Connection ID.
            updates: Dict of fields to update. May include 'config', 'name', 'enabled'.
            fernet_key: Fernet key for encryption/decryption.

        Returns:
            Updated connection dict with masked secrets, or None if not found.
        """
        from metatron.connectors.schemas import merge_config, validate_config
        from metatron.storage.encryption import decrypt_value, encrypt_value

        logger.info("postgres.connection.update", connection_id=connection_id)

        now = datetime.now(UTC)

        async with self._engine.begin() as conn:
            # Fetch current row
            result = await conn.execute(
                text("""
                    SELECT id, workspace_id, connector_type, name,
                           config_encrypted, status, enabled, error_message,
                           last_synced_at, created_at, updated_at
                    FROM connections
                    WHERE id = :id
                    FOR UPDATE
                """),
                {"id": connection_id},
            )
            row = result.first()
            if not row:
                return None

            m = row._mapping
            connector_type = m["connector_type"]

            # Build SET clauses
            set_parts = ["updated_at = :updated_at"]
            params: dict[str, Any] = {"id": connection_id, "updated_at": now}

            if "name" in updates:
                set_parts.append("name = :name")
                params["name"] = updates["name"]

            if "enabled" in updates:
                set_parts.append("enabled = :enabled")
                params["enabled"] = updates["enabled"]

            if "config" in updates:
                old_config = json.loads(decrypt_value(m["config_encrypted"], fernet_key))
                new_config = merge_config(connector_type, old_config, updates["config"])

                errors = validate_config(connector_type, new_config)
                if errors:
                    raise ValueError("; ".join(errors))

                encrypted = encrypt_value(json.dumps(new_config), fernet_key)
                set_parts.append("config_encrypted = :config_encrypted")
                params["config_encrypted"] = encrypted

            await conn.execute(
                text(f"UPDATE connections SET {', '.join(set_parts)} WHERE id = :id"),
                params,
            )

        # Return updated connection with masked secrets
        return await self.get_connection(connection_id, fernet_key)

    async def delete_connection(self, connection_id: str) -> bool:
        """Delete a connection by ID.

        Args:
            connection_id: Connection ID.

        Returns:
            True if deleted, False if not found.
        """
        logger.info("postgres.connection.delete", connection_id=connection_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM connections WHERE id = :id"),
                {"id": connection_id},
            )
            return result.rowcount > 0  # type: ignore[union-attr]

    async def update_connection_status(
        self,
        connection_id: str,
        status: str,
        error_message: str | None = None,
        last_synced_at: datetime | None = None,
    ) -> None:
        """Update connection status, error message, and optional sync timestamp."""
        logger.info(
            "postgres.connection.update_status",
            connection_id=connection_id,
            status=status,
        )

        set_parts = ["status = :status", "error_message = :error_message"]
        params: dict[str, Any] = {
            "id": connection_id,
            "status": status,
            "error_message": error_message,
        }
        if last_synced_at is not None:
            set_parts.append("last_synced_at = :last_synced_at")
            params["last_synced_at"] = last_synced_at

        async with self._engine.begin() as conn:
            await conn.execute(
                text(f"UPDATE connections SET {', '.join(set_parts)} WHERE id = :id"),
                params,
            )

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

    # --- Sync logs ---

    async def create_sync_log(
        self,
        sync_id: str,
        workspace_id: str,
        connection_id: str | None,
        connector_type: str,
    ) -> None:
        """Insert a ``sync_logs`` row with status='running'.

        Called synchronously from ``trigger_sync`` BEFORE the background task
        is scheduled, so that a record exists even if the task dies before
        reaching its ``finally`` block.
        """
        logger.info(
            "postgres.sync_log.create",
            sync_id=sync_id,
            workspace_id=workspace_id,
            connector_type=connector_type,
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO sync_logs "
                    "(id, workspace_id, connection_id, connector_type, status, "
                    " documents_fetched, documents_new, documents_updated, "
                    " documents_skipped, errors, duration_ms, source_title, "
                    " qdrant_chunks, created_at) "
                    "VALUES (:id, :ws, :conn, :ct, 'running', "
                    "        0, 0, 0, 0, '[]'::jsonb, 0, :title, 0, :now)"
                ),
                {
                    "id": sync_id,
                    "ws": workspace_id,
                    "conn": connection_id,
                    "ct": connector_type,
                    "title": f"{connector_type.capitalize()} Sync",
                    "now": datetime.now(UTC),
                },
            )

    async def update_sync_log(
        self,
        sync_id: str,
        status: str,
        documents_fetched: int | None = None,
        documents_new: int | None = None,
        documents_updated: int | None = None,
        documents_skipped: int | None = None,
        qdrant_chunks: int | None = None,
        errors: list[str] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Finalize a sync_logs row. Only non-None fields are updated."""
        logger.info("postgres.sync_log.update", sync_id=sync_id, status=status)

        set_parts = ["status = :status"]
        params: dict[str, Any] = {"id": sync_id, "status": status}

        if documents_fetched is not None:
            set_parts.append("documents_fetched = :df")
            params["df"] = documents_fetched
        if documents_new is not None:
            set_parts.append("documents_new = :dn")
            params["dn"] = documents_new
        if documents_updated is not None:
            set_parts.append("documents_updated = :du")
            params["du"] = documents_updated
        if documents_skipped is not None:
            set_parts.append("documents_skipped = :ds")
            params["ds"] = documents_skipped
        if qdrant_chunks is not None:
            set_parts.append("qdrant_chunks = :qc")
            params["qc"] = qdrant_chunks
        if errors is not None:
            set_parts.append("errors = CAST(:err AS jsonb)")
            params["err"] = json.dumps(errors)
        if duration_ms is not None:
            set_parts.append("duration_ms = :dur")
            params["dur"] = duration_ms

        async with self._engine.begin() as conn:
            await conn.execute(
                text(f"UPDATE sync_logs SET {', '.join(set_parts)} WHERE id = :id"),
                params,
            )

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

    # --- Raw Documents (Document Store) ---

    async def upsert_raw_documents(
        self,
        workspace_id: str,
        documents: list[RawDocument],
        connector_type: str,
        connection_id: str | None = None,
    ) -> dict[str, int]:
        """Upsert raw documents, skipping unchanged content.

        Args:
            workspace_id: Workspace scope.
            documents: List of RawDocument objects to upsert.
            connector_type: Connector type (confluence, jira, etc.).
            connection_id: Optional connection ID.

        Returns:
            Dict with counts: {"new": N, "updated": N, "unchanged": N}.
        """
        logger.info(
            "postgres.raw_documents.upsert",
            workspace_id=workspace_id,
            count=len(documents),
        )
        counts = {"new": 0, "updated": 0, "unchanged": 0, "changed_source_ids": []}
        now = datetime.now(UTC)

        async with self._engine.begin() as conn:
            for doc in documents:
                content_hash = hashlib.sha256(doc.content.encode()).hexdigest()

                # Check if document already exists
                result = await conn.execute(
                    text("""
                        SELECT id, content_hash, qdrant_synced
                        FROM raw_documents
                        WHERE workspace_id = :workspace_id
                          AND connector_type = :connector_type
                          AND source_id = :source_id
                    """),
                    {
                        "workspace_id": workspace_id,
                        "connector_type": connector_type,
                        "source_id": doc.source_id,
                    },
                )
                existing = result.first()

                if existing is None:
                    # New document — insert
                    await conn.execute(
                        text("""
                            INSERT INTO raw_documents
                            (id, workspace_id, connector_type, connection_id,
                             source_id, title, content, url, author,
                             content_hash, metadata, source_role,
                             qdrant_synced, graph_synced,
                             fetched_at, created_at, updated_at,
                             source_created_at, source_updated_at)
                            VALUES
                            (:id, :workspace_id, :connector_type, :connection_id,
                             :source_id, :title, :content, :url, :author,
                             :content_hash, CAST(:metadata AS jsonb), :source_role,
                             false, false,
                             :now, :now, :now,
                             :source_created_at, :source_updated_at)
                        """),
                        {
                            "id": doc.id,
                            "workspace_id": workspace_id,
                            "connector_type": connector_type,
                            "connection_id": connection_id,
                            "source_id": doc.source_id,
                            "title": doc.title,
                            "content": doc.content,
                            "url": doc.url,
                            "author": doc.author,
                            "content_hash": content_hash,
                            "metadata": json.dumps(doc.metadata),
                            "source_role": doc.source_role,
                            "now": now,
                            "source_created_at": doc.created_at,
                            "source_updated_at": doc.updated_at,
                        },
                    )
                    counts["new"] += 1
                    counts["changed_source_ids"].append(doc.source_id)
                elif existing._mapping["content_hash"] != content_hash:
                    # Content changed — update and reset sync flags
                    await conn.execute(
                        text("""
                            UPDATE raw_documents
                            SET title = :title,
                                content = :content,
                                url = :url,
                                author = :author,
                                content_hash = :content_hash,
                                metadata = CAST(:metadata AS jsonb),
                                source_role = :source_role,
                                qdrant_synced = false,
                                graph_synced = false,
                                qdrant_synced_at = NULL,
                                graph_synced_at = NULL,
                                fetched_at = :now,
                                updated_at = :now,
                                source_updated_at = :source_updated_at
                            WHERE id = :id
                        """),
                        {
                            "id": existing._mapping["id"],
                            "title": doc.title,
                            "content": doc.content,
                            "url": doc.url,
                            "author": doc.author,
                            "content_hash": content_hash,
                            "metadata": json.dumps(doc.metadata),
                            "source_role": doc.source_role,
                            "now": now,
                            "source_updated_at": doc.updated_at,
                        },
                    )
                    counts["updated"] += 1
                    counts["changed_source_ids"].append(doc.source_id)
                else:
                    # Content unchanged — just bump fetched_at
                    await conn.execute(
                        text("""
                            UPDATE raw_documents
                            SET fetched_at = :now
                            WHERE id = :id
                        """),
                        {"id": existing._mapping["id"], "now": now},
                    )
                    counts["unchanged"] += 1
                    # If not yet synced to Qdrant (e.g. reindex), still needs processing
                    if not existing._mapping.get("qdrant_synced", True):
                        counts["changed_source_ids"].append(doc.source_id)

        return counts

    async def get_unsynced_documents(
        self,
        workspace_id: str,
        target: str = "qdrant",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch documents not yet synced to a target store.

        Args:
            workspace_id: Workspace scope.
            target: Sync target — "qdrant" or "graph".
            limit: Max documents to return.

        Returns:
            List of raw document dicts.
        """
        if target not in ("qdrant", "graph"):
            raise ValueError(f"Invalid sync target: {target}")

        logger.info(
            "postgres.raw_documents.unsynced",
            workspace_id=workspace_id,
            target=target,
            limit=limit,
        )

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT * FROM raw_documents
                    WHERE workspace_id = :workspace_id
                      AND NOT {target}_synced
                    ORDER BY fetched_at
                    LIMIT :limit
                """),
                {"workspace_id": workspace_id, "limit": limit},
            )
            return [dict(row._mapping) for row in result]

    async def mark_documents_synced(
        self,
        doc_ids: list[str],
        target: str = "qdrant",
    ) -> None:
        """Mark documents as synced to a target store.

        Args:
            doc_ids: List of document IDs to mark.
            target: Sync target — "qdrant" or "graph".
        """
        if target not in ("qdrant", "graph"):
            raise ValueError(f"Invalid sync target: {target}")
        if not doc_ids:
            return

        logger.info(
            "postgres.raw_documents.mark_synced",
            target=target,
            count=len(doc_ids),
        )

        async with self._engine.begin() as conn:
            await conn.execute(
                text(f"""
                    UPDATE raw_documents
                    SET {target}_synced = true,
                        {target}_synced_at = NOW()
                    WHERE id = ANY(:ids)
                """),
                {"ids": doc_ids},
            )

    async def mark_documents_synced_by_source(
        self,
        workspace_id: str,
        connector_type: str,
        source_ids: list[str],
        target: str = "qdrant",
    ) -> None:
        """Mark documents as synced using natural keys instead of PG IDs.

        Args:
            workspace_id: Workspace scope.
            connector_type: Connector type.
            source_ids: List of source-specific document IDs.
            target: Sync target — "qdrant" or "graph".
        """
        if target not in ("qdrant", "graph"):
            raise ValueError(f"Invalid sync target: {target}")
        if not source_ids:
            return

        logger.info(
            "postgres.raw_documents.mark_synced_by_source",
            target=target,
            count=len(source_ids),
        )

        async with self._engine.begin() as conn:
            await conn.execute(
                text(f"""
                    UPDATE raw_documents
                    SET {target}_synced = true,
                        {target}_synced_at = NOW()
                    WHERE workspace_id = :workspace_id
                      AND connector_type = :connector_type
                      AND source_id = ANY(:source_ids)
                """),
                {
                    "workspace_id": workspace_id,
                    "connector_type": connector_type,
                    "source_ids": source_ids,
                },
            )

    async def get_raw_document(
        self,
        workspace_id: str,
        connector_type: str,
        source_id: str,
    ) -> dict[str, Any] | None:
        """Fetch a single raw document by natural key.

        Args:
            workspace_id: Workspace scope.
            connector_type: Connector type.
            source_id: Source-specific document ID.

        Returns:
            Raw document dict or None.
        """
        logger.info(
            "postgres.raw_document.get",
            workspace_id=workspace_id,
            connector_type=connector_type,
            source_id=source_id,
        )

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM raw_documents
                    WHERE workspace_id = :workspace_id
                      AND connector_type = :connector_type
                      AND source_id = :source_id
                """),
                {
                    "workspace_id": workspace_id,
                    "connector_type": connector_type,
                    "source_id": source_id,
                },
            )
            row = result.first()
            if not row:
                return None
            return dict(row._mapping)

    # --- Dedup Fingerprints ---

    async def batch_load_fingerprints(self, workspace_id: str) -> dict[int, str]:
        """Load all fingerprints for a workspace.

        Returns:
            Dict mapping fingerprint (unsigned 64-bit) to doc_label.
        """
        logger.info("postgres.fingerprints.load", workspace_id=workspace_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT fingerprint, doc_label
                    FROM dedup_fingerprints
                    WHERE workspace_id = :workspace_id
                """),
                {"workspace_id": workspace_id},
            )
            return {
                _from_pg_bigint(row._mapping["fingerprint"]): row._mapping["doc_label"]
                for row in result
            }

    async def save_fingerprints(
        self,
        workspace_id: str,
        fingerprints: list[tuple[str, int]],
    ) -> int:
        """Batch-insert new fingerprints, skipping duplicates.

        Args:
            workspace_id: Workspace scope.
            fingerprints: List of (doc_label, fingerprint) tuples.

        Returns:
            Number of rows actually inserted.
        """
        if not fingerprints:
            return 0

        logger.info(
            "postgres.fingerprints.save",
            workspace_id=workspace_id,
            count=len(fingerprints),
        )

        inserted = 0
        async with self._engine.begin() as conn:
            for doc_label, fp in fingerprints:
                result = await conn.execute(
                    text("""
                        INSERT INTO dedup_fingerprints
                        (id, workspace_id, doc_label, fingerprint)
                        VALUES (:id, :workspace_id, :doc_label, :fingerprint)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": uuid4().hex,
                        "workspace_id": workspace_id,
                        "doc_label": doc_label,
                        "fingerprint": _to_pg_bigint(fp),
                    },
                )
                inserted += result.rowcount  # type: ignore[operator]

        return inserted

    async def delete_fingerprints_by_doc(self, workspace_id: str, doc_label: str) -> int:
        """Delete all fingerprints for a document.

        Args:
            workspace_id: Workspace scope.
            doc_label: Document label to delete fingerprints for.

        Returns:
            Number of rows deleted.
        """
        logger.info(
            "postgres.fingerprints.delete",
            workspace_id=workspace_id,
            doc_label=doc_label,
        )

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    DELETE FROM dedup_fingerprints
                    WHERE workspace_id = :workspace_id
                      AND doc_label = :doc_label
                """),
                {"workspace_id": workspace_id, "doc_label": doc_label},
            )
            return result.rowcount  # type: ignore[return-value]

    async def close(self) -> None:
        """Dispose of the engine and its connection pool."""
        await self._engine.dispose()
