"""PostgreSQL async store — CRUD for all tables.

Uses asyncpg via SQLAlchemy async engine. All operations are
workspace-scoped where applicable. No ORM models — we use
raw SQL with parameterized queries for clarity and control.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from metronix.core.models import (
    DocumentVersion,
    FileRecord,
    LifecycleStatus,
    RawDocument,
    Skill,
    User,
    Workspace,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
        from metronix.connectors.schemas import mask_secrets, validate_config
        from metronix.storage.encryption import encrypt_value

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
            "sync_cron": None,  # populated by set_connection_schedule after create
            "next_run_at": None,
        }

    async def list_connections(self, workspace_id: str, fernet_key: str) -> list[dict]:
        """List all connections for a workspace with masked secrets.

        Args:
            workspace_id: Workspace to list connections for.
            fernet_key: Fernet key for decrypting config (to then mask).

        Returns:
            List of connection dicts with masked secret fields.
        """
        from metronix.connectors.schemas import mask_secrets
        from metronix.storage.encryption import decrypt_value

        logger.info("postgres.connections.list", workspace_id=workspace_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, workspace_id, connector_type, name,
                           config_encrypted, status, enabled, error_message,
                           last_synced_at, created_at, updated_at,
                           sync_cron, next_run_at
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
                    "sync_cron": m["sync_cron"],
                    "next_run_at": m["next_run_at"].isoformat() if m["next_run_at"] else None,
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
        from metronix.connectors.schemas import mask_secrets
        from metronix.storage.encryption import decrypt_value

        logger.info("postgres.connection.get", connection_id=connection_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, workspace_id, connector_type, name,
                           config_encrypted, status, enabled, error_message,
                           last_synced_at, created_at, updated_at,
                           sync_cron, next_run_at
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
            "sync_cron": m["sync_cron"],
            "next_run_at": m["next_run_at"].isoformat() if m["next_run_at"] else None,
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
        from metronix.storage.encryption import decrypt_value

        logger.info("postgres.connection.get_decrypted", connection_id=connection_id)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, workspace_id, connector_type, name,
                           config_encrypted, status, enabled, error_message,
                           last_synced_at, created_at, updated_at,
                           sync_cron, next_run_at
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
            "sync_cron": m["sync_cron"],
            "next_run_at": m["next_run_at"].isoformat() if m["next_run_at"] else None,
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
        from metronix.connectors.schemas import merge_config, validate_config
        from metronix.storage.encryption import decrypt_value, encrypt_value

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
        """Update connection status, error message, and optional sync timestamp.

        **Asymmetric ``None`` semantics — read carefully:**

        * ``error_message=None`` → SQL writes ``error_message = NULL``. This
          unconditionally clears any previously-stored error message.
          (Pre-existing behaviour; not changed by MTRNIX-332.)
        * ``last_synced_at=None`` → the cursor column is NOT touched (the
          ``SET last_synced_at = ...`` clause is omitted). This is the
          mechanism used by ``_run_connection_sync`` to leave the cursor
          unchanged on failed syncs — advancing it would silently drop
          documents updated between the last good sync and the failure.

        The divergence is an artefact of the cursor-trap fix in MTRNIX-332;
        unifying the two patterns is a separate follow-up.
        """
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

    async def claim_connection_for_autosync(
        self, connection_id: str, next_run_at: datetime
    ) -> bool:
        """Atomically claim a connection for autosync.

        Sets ``status='syncing'`` and advances ``next_run_at`` in a single
        conditional UPDATE. Returns True iff the row was claimed (i.e. it was
        not already syncing, was enabled, had a non-NULL cron schedule, and was
        due). This makes the claim multi-replica-safe: only one process wins.

        Args:
            connection_id: Connection to claim.
            next_run_at: Next scheduled time to write when claiming the row.

        Returns:
            True if this call won the claim, False if another process already
            has the row or the row is no longer due.
        """
        logger.debug(
            "postgres.connection.claim_autosync",
            connection_id=connection_id,
            next_run_at=next_run_at.isoformat(),
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    UPDATE connections
                       SET status = 'syncing', next_run_at = :next_run_at
                     WHERE id = :id
                       AND status != 'syncing'
                       AND enabled = true
                       AND sync_cron IS NOT NULL
                       AND (next_run_at IS NULL OR next_run_at <= now())
                    RETURNING id
                """),
                {"id": connection_id, "next_run_at": next_run_at},
            )
            row = result.first()
        return row is not None

    async def list_due_autosync_connections(self, limit: int) -> list[dict[str, Any]]:
        """Return connections that are due for an autosync tick.

        A connection is due when it is enabled, has a non-NULL sync_cron,
        is not already syncing, and its ``next_run_at`` is either NULL (treat
        as "due now") or in the past. Results are ordered by ``next_run_at``
        ascending with NULLs first (oldest / never-run connections first).

        Note: this query is intentionally NOT workspace-scoped. The scheduler
        runs across all workspaces; workspace isolation is enforced inside
        ``_run_connection_sync`` (see ADR 2026-06-09-autosync-architecture.md).

        Args:
            limit: Maximum rows to return per tick.

        Returns:
            List of lightweight dicts: ``{id, connector_type, sync_cron,
            workspace_id}``. No decryption — config is not fetched here.
        """
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, connector_type, sync_cron, workspace_id
                      FROM connections
                     WHERE enabled = true
                       AND sync_cron IS NOT NULL
                       AND status != 'syncing'
                       AND (next_run_at IS NULL OR next_run_at <= now())
                     ORDER BY next_run_at ASC NULLS FIRST
                     LIMIT :limit
                """),
                {"limit": limit},
            )
            rows = result.fetchall()
        return [
            {
                "id": row._mapping["id"],
                "connector_type": row._mapping["connector_type"],
                "sync_cron": row._mapping["sync_cron"],
                "workspace_id": row._mapping["workspace_id"],
            }
            for row in rows
        ]

    async def set_connection_schedule(
        self,
        connection_id: str,
        sync_cron: str | None,
        next_run_at: datetime | None,
    ) -> None:
        """Update ``sync_cron`` and ``next_run_at`` for a connection.

        Pass ``None`` for both to clear the schedule (disables autosync).

        Args:
            connection_id: Target connection.
            sync_cron: New cron expression, or None to clear.
            next_run_at: Pre-computed next run time (UTC), or None.
        """
        logger.debug(
            "postgres.connection.set_schedule",
            connection_id=connection_id,
            sync_cron=sync_cron,
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE connections
                       SET sync_cron = :sync_cron, next_run_at = :next_run_at
                     WHERE id = :id
                """),
                {
                    "id": connection_id,
                    "sync_cron": sync_cron,
                    "next_run_at": next_run_at,
                },
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

    # --- Sync logs ---

    async def create_sync_log(
        self,
        sync_id: str,
        workspace_id: str,
        connection_id: str | None,
        connector_type: str,
        trigger: str = "manual",
    ) -> None:
        """Insert a ``sync_logs`` row with status='running'.

        Called synchronously from ``trigger_sync`` BEFORE the background task
        is scheduled, so that a record exists even if the task dies before
        reaching its ``finally`` block.

        ``trigger`` records the origin of the sync: ``"manual"`` (user-initiated
        via the API) or ``"scheduled"`` (autosync scheduler).
        """
        logger.info(
            "postgres.sync_log.create",
            sync_id=sync_id,
            workspace_id=workspace_id,
            connector_type=connector_type,
            trigger=trigger,
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO sync_logs "
                    "(id, workspace_id, connection_id, connector_type, status, "
                    " documents_fetched, documents_new, documents_updated, "
                    " documents_skipped, errors, duration_ms, source_title, "
                    " qdrant_chunks, trigger, created_at) "
                    "VALUES (:id, :ws, :conn, :ct, 'running', "
                    "        0, 0, 0, 0, '[]'::jsonb, 0, :title, 0, :trigger, :now)"
                ),
                {
                    "id": sync_id,
                    "ws": workspace_id,
                    "conn": connection_id,
                    "ct": connector_type,
                    "title": f"{connector_type.capitalize()} Sync",
                    "trigger": trigger,
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

    @asynccontextmanager
    async def graph_processing_lock(self, workspace_id: str) -> AsyncIterator[bool]:
        """Per-workspace advisory lock for graph extraction.

        Graph processing funnels through ``process_all_unsynced_graphs``, called
        by the graph sweeper, connector syncs, and uploads — none of which claim
        the rows they select. This lock serialises those callers per workspace so
        two passes don't redundantly run LLM extraction over the same
        ``graph_synced=false`` documents.

        Yields ``True`` if the lock was acquired (caller should proceed) or
        ``False`` if another pass already holds it (caller should skip and let
        the next sweep retry). Uses a dedicated AUTOCOMMIT connection so the
        session-level lock is not tied to a long-open transaction.
        """
        # Positive signed-bigint lock id, same derivation style as the migration
        # lock (md5 -> truncate -> mod 2**63).
        lock_id = int(
            hashlib.md5(f"metronix_graph:{workspace_id}".encode()).hexdigest()[:15], 16
        ) % (2**63)
        conn = await self._engine.connect()
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        acquired = False
        try:
            acquired = bool(
                (
                    await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_id})
                ).scalar()
            )
            yield acquired
        finally:
            if acquired:
                with suppress(Exception):
                    await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id})
            await conn.close()

    async def list_workspaces_with_unsynced_graphs(self) -> list[str]:
        """Return workspace ids that have at least one ``graph_synced=false`` row.

        Used by the graph sweeper to find which workspaces still have a graph
        backlog, without scanning every workspace.
        """
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT DISTINCT workspace_id
                    FROM raw_documents
                    WHERE NOT graph_synced
                """)
            )
            return [row._mapping["workspace_id"] for row in result]

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

    # --- Raw document lifecycle (MTRNIX-313) ---

    @staticmethod
    def _row_to_raw_document(row: Any) -> RawDocument:
        """Map a ``raw_documents`` row to a :class:`RawDocument` dataclass.

        Understands the seven Phase-B lifecycle columns; missing keys fall
        through to the dataclass defaults so stores on databases that pre-date
        migration 018 still work (though the migration is required for the
        freshness worker to be useful).
        """
        m = row._mapping
        raw_status = m.get("status")
        try:
            status = LifecycleStatus(raw_status) if raw_status else LifecycleStatus.ACTIVE
        except ValueError:
            status = LifecycleStatus.ACTIVE
        metadata = m.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}
        return RawDocument(
            id=m["id"],
            workspace_id=m.get("workspace_id", ""),
            connector_type=m.get("connector_type", ""),
            connection_id=m.get("connection_id"),
            source_id=m.get("source_id", ""),
            title=m.get("title", ""),
            content=m.get("content", ""),
            url=m.get("url", ""),
            author=m.get("author", ""),
            content_hash=m.get("content_hash", ""),
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
            source_role=m.get("source_role", "knowledge_base"),
            qdrant_synced=bool(m.get("qdrant_synced", False)),
            graph_synced=bool(m.get("graph_synced", False)),
            fetched_at=m.get("fetched_at"),
            created_at=m.get("created_at"),
            updated_at=m.get("updated_at"),
            status=status,
            freshness_score=float(m.get("freshness_score", 0.5) or 0.5),
            superseded_by=m.get("superseded_by"),
            valid_until=m.get("valid_until"),
            evidence_count=int(m.get("evidence_count", 0) or 0),
            verification_state=m.get("verification_state"),
            last_freshness_run_at=m.get("last_freshness_run_at"),
        )

    async def get_raw_document_by_id(
        self,
        workspace_id: str,
        raw_doc_id: str,
    ) -> RawDocument | None:
        """Fetch a raw_document row by (workspace_id, id).

        Freshness-path lookup: the worker and producer already know the PG id,
        and adapters need the full :class:`RawDocument` dataclass rather than
        the raw row dict returned by :meth:`get_raw_document`.
        """
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT * FROM raw_documents WHERE workspace_id = :workspace_id AND id = :id"
                ),
                {"workspace_id": workspace_id, "id": raw_doc_id},
            )
            row = result.first()
            return self._row_to_raw_document(row) if row else None

    async def update_raw_document_lifecycle(
        self,
        workspace_id: str,
        raw_doc_id: str,
        *,
        status: LifecycleStatus | None = None,
        freshness_score: float | None = None,
        superseded_by: str | None = None,
        evidence_count: int | None = None,
        verification_state: str | None = None,
        valid_until: datetime | None = None,
        last_freshness_run_at: datetime | None = None,
    ) -> None:
        """Update lifecycle columns on a ``raw_documents`` row (workspace-scoped).

        Only columns passed as non-``None`` are updated; passing no fields is a
        silent no-op. Every UPDATE carries ``workspace_id`` in the WHERE clause
        so a collision on ``id`` across tenants cannot leak.
        """
        updates: dict[str, object] = {}
        if status is not None:
            updates["status"] = status.value
        if freshness_score is not None:
            updates["freshness_score"] = freshness_score
        if superseded_by is not None:
            updates["superseded_by"] = superseded_by
        if evidence_count is not None:
            updates["evidence_count"] = evidence_count
        if verification_state is not None:
            updates["verification_state"] = verification_state
        if valid_until is not None:
            updates["valid_until"] = valid_until
        if last_freshness_run_at is not None:
            updates["last_freshness_run_at"] = last_freshness_run_at
        if not updates:
            return
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE raw_documents SET {set_clause} "
                    "WHERE workspace_id = :workspace_id AND id = :id"
                ),
                {**updates, "workspace_id": workspace_id, "id": raw_doc_id},
            )

    # --- Raw document list helpers (memory-scopes Phase 1, MTRNIX-memory-scopes) ---

    async def list_raw_documents(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RawDocument]:
        """Return paginated raw_documents for a workspace, ordered by updated_at DESC, id ASC.

        Workspace-scoped. Reuses :meth:`_row_to_raw_document` for consistent field mapping.
        Stable pagination: ``updated_at DESC, id ASC`` ensures deterministic ordering even
        when multiple rows share the same ``updated_at`` timestamp.
        """
        logger.info(
            "postgres.raw_documents.list",
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM raw_documents
                    WHERE workspace_id = :workspace_id
                    ORDER BY updated_at DESC, id ASC
                    LIMIT :limit OFFSET :offset
                """),
                {"workspace_id": workspace_id, "limit": limit, "offset": offset},
            )
            return [self._row_to_raw_document(row) for row in result]

    async def list_document_workspaces(self) -> list[str]:
        """Return distinct workspace_ids present in raw_documents."""
        async with self._engine.begin() as conn:
            result = await conn.execute(text("SELECT DISTINCT workspace_id FROM raw_documents"))
            return [str(r[0]) for r in result.fetchall()]

    async def list_raw_documents_keyset(
        self,
        workspace_id: str,
        *,
        after_updated_at: object | None,
        after_id: str | None,
        limit: int = 200,
    ) -> list[RawDocument]:
        """Keyset page over (updated_at DESC, id ASC). Pass after_* = None for first page."""
        params: dict = {"workspace_id": workspace_id, "limit": limit}
        where = "workspace_id = :workspace_id"
        if after_updated_at is not None and after_id is not None:
            # Keyset for ORDER BY updated_at DESC, id ASC: the next page is rows
            # strictly older, or same timestamp with a larger id (id ASC tiebreak).
            # A plain row-value `(updated_at, id) < (...)` is WRONG here — it treats
            # id as DESC and both skips and duplicates rows on updated_at ties.
            where += (
                " AND (updated_at < :after_updated_at "
                "OR (updated_at = :after_updated_at AND id > :after_id))"
            )
            params["after_updated_at"] = after_updated_at
            params["after_id"] = after_id
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"SELECT * FROM raw_documents WHERE {where} "
                    "ORDER BY updated_at DESC, id ASC LIMIT :limit"
                ),
                params,
            )
            return [self._row_to_raw_document(row) for row in result]

    async def count_raw_documents(self, workspace_id: str) -> int:
        """Return the total number of raw_documents for a workspace.

        Used alongside :meth:`list_raw_documents` to populate ``has_more`` and
        ``total`` fields in paginated responses. For workspaces with >100 k
        documents a partial index or ``estimate_count`` should be considered —
        see TODO in the knowledge route docstring.
        """
        logger.info(
            "postgres.raw_documents.count",
            workspace_id=workspace_id,
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("SELECT count(*) FROM raw_documents WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            )
            row = result.first()
            return int(row._mapping["count"]) if row else 0

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
