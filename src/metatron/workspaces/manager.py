"""Workspace manager — handles workspace CRUD and activation.

Migrated from PoC metatron/workspaces/manager.py.
Supports both in-memory and persistent storage (Neo4j).

# TODO: async migration (existing sync surface)
# MTRNIX-352 (T2): new async lifecycle methods added below existing sync surface.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from threading import Lock
from typing import TYPE_CHECKING, Any

import structlog
from qdrant_client import AsyncQdrantClient

from metatron.storage.neo4j_graph import delete_workspace_graph
from metatron.storage.qdrant import get_collection_name
from metatron.workspaces.models import Workspace, WorkspaceStats

if TYPE_CHECKING:
    from metatron.chat.persistence import ChatPersistence
    from metatron.storage.postgres import PostgresStore
    from metatron.workspaces.bootstrap.models import BootstrapState
    from metatron.workspaces.bootstrap.runner import BootstrapRunner
    from metatron.workspaces.bootstrap.store import BootstrapStateStore

logger = structlog.get_logger()


class WorkspaceManager:
    """Manager for workspace operations.

    Supports both in-memory and persistent storage (Neo4j).

    Backward-compatible constructor — ``WorkspaceManager()`` (zero args) still works.
    ASOC lifecycle methods (bootstrap / delete) require the optional kwargs below to
    be injected.  archive/unarchive removed per grooming 2026-05 (MTRNIX-370);
    archive = delete.
    """

    def __init__(
        self,
        use_persistence: bool = True,
        *,
        bootstrap_store: BootstrapStateStore | None = None,
        chat_persistence: ChatPersistence | None = None,
        pg_store: PostgresStore | None = None,
        bootstrap_runner: BootstrapRunner | None = None,
    ) -> None:
        self._workspaces: dict[str, Workspace] = {}
        self._active_workspace: dict[str, str] = {}
        self._lock = Lock()
        self._stats: dict[str, WorkspaceStats] = {}
        self._persistence = None
        self._use_persistence = False
        # ASOC lifecycle deps (MTRNIX-352)
        self._bootstrap_store = bootstrap_store
        self._chat_persistence = chat_persistence
        self._pg_store = pg_store
        self._bootstrap_runner = bootstrap_runner
        self._async_lock: asyncio.Lock | None = None  # lazy

        if use_persistence:
            try:
                from metatron.core.config import Settings

                settings = Settings()
                if settings.workspace_persistence in ("memgraph", "neo4j"):
                    from metatron.workspaces.persistence import get_workspace_persistence

                    self._persistence = get_workspace_persistence()
                    self._use_persistence = True
                    self._load_from_persistence()
                    logger.info("workspace.persistence.enabled", backend="neo4j")
            except Exception as e:
                logger.warning("workspace.persistence.failed", error=str(e))

        self._ensure_default_workspace()

    def _load_from_persistence(self) -> None:
        if not self._persistence:
            return
        try:
            workspaces = self._persistence.load_all_workspaces()
            for ws in workspaces:
                self._workspaces[ws.workspace_id] = ws
                # Sync each workspace to PostgreSQL
                self._sync_workspace_to_postgres(ws)
            logger.info("workspace.loaded", count=len(workspaces))
        except Exception as e:
            logger.error("workspace.load.failed", error=str(e))
        try:
            self._stats = self._persistence.load_all_workspace_stats()
        except Exception as e:
            logger.error("workspace.stats.load.failed", error=str(e))

    def _sync_workspace_to_postgres(self, workspace: Workspace) -> None:
        """Sync workspace to PostgreSQL for foreign key integrity (minimal fields only)."""
        try:
            from sqlalchemy import text

            from metatron.storage.pg_connection import get_session

            with get_session() as session:
                # Check if workspace exists
                result = session.execute(
                    text("SELECT id FROM workspaces WHERE id = :id"),
                    {"id": workspace.workspace_id},
                ).fetchone()

                if result:
                    # Update existing
                    session.execute(
                        text("UPDATE workspaces SET name = :name, slug = :slug WHERE id = :id"),
                        {
                            "id": workspace.workspace_id,
                            "name": workspace.name,
                            "slug": workspace.workspace_id.lower(),
                        },
                    )
                else:
                    # Create new (only fields that exist in migration 001)
                    session.execute(
                        text("""
                            INSERT INTO workspaces (id, name, slug, created_at)
                            VALUES (:id, :name, :slug, NOW())
                        """),
                        {
                            "id": workspace.workspace_id,
                            "name": workspace.name,
                            "slug": workspace.workspace_id.lower(),
                        },
                    )

                session.commit()
                logger.info("workspace.postgres.synced", workspace_id=workspace.workspace_id)
        except Exception as e:
            logger.warning(
                "workspace.postgres.sync.failed", workspace_id=workspace.workspace_id, error=str(e)
            )

    def _ensure_default_workspace(self) -> None:
        from metatron.core.config import Settings

        settings = Settings()
        default_id = settings.default_workspace_id
        default_name = settings.default_workspace_name

        if default_id not in self._workspaces:
            default = Workspace(
                workspace_id=default_id,
                name=default_name,
                description=f"Main workspace for {default_id} project",
                user_id="system",
            )
            self._workspaces[default_id] = default
            if self._persistence:
                try:
                    self._persistence.save_workspace(default)
                except Exception as e:
                    logger.warning("workspace.persist.default.failed", error=str(e))
            # Sync to PostgreSQL
            self._sync_workspace_to_postgres(default)
            logger.info("workspace.default.created", workspace_id=default_id)

    def create_workspace(
        self,
        name: str,
        description: str | None = None,
        user_id: str = "user",
        workspace_id: str | None = None,
    ) -> Workspace:
        with self._lock:
            if workspace_id is None:
                workspace_id = f"ws_{uuid.uuid4().hex[:8]}"
            if workspace_id in self._workspaces:
                raise ValueError(f"Workspace '{workspace_id}' already exists")

            workspace = Workspace(
                workspace_id=workspace_id,
                name=name,
                description=description,
                user_id=user_id,
            )
            self._workspaces[workspace_id] = workspace
            if self._persistence:
                try:
                    self._persistence.save_workspace(workspace)
                except Exception as e:
                    logger.warning("workspace.persist.failed", error=str(e))
            # Sync to PostgreSQL
            self._sync_workspace_to_postgres(workspace)
            return workspace

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        from metatron.core.utils import normalize_workspace_id

        workspace_id = normalize_workspace_id(workspace_id)
        return self._workspaces.get(workspace_id)

    def list_workspaces(self, user_id: str | None = None) -> list[Workspace]:
        workspaces = list(self._workspaces.values())
        if user_id:
            from metatron.core.config import Settings

            default_id = Settings().default_workspace_id
            workspaces = [
                w for w in workspaces if w.user_id == user_id or w.workspace_id == default_id
            ]
        workspaces.sort(key=lambda w: w.created_at or "", reverse=True)
        return workspaces

    def delete_workspace(self, workspace_id: str) -> bool:
        from metatron.core.config import Settings

        default_id = Settings().default_workspace_id

        with self._lock:
            if workspace_id == default_id:
                raise ValueError(f"Cannot delete default workspace '{default_id}'")
            if workspace_id not in self._workspaces:
                return False
            for uid, ws_id in list(self._active_workspace.items()):
                if ws_id == workspace_id:
                    self._active_workspace[uid] = default_id
            del self._workspaces[workspace_id]
            if self._persistence:
                try:
                    self._persistence.delete_workspace(workspace_id)
                except Exception as e:
                    logger.warning("workspace.persist.delete.failed", error=str(e))
            return True

    def set_active_workspace(self, user_id: str, workspace_id: str) -> bool:
        if workspace_id not in self._workspaces:
            return False
        with self._lock:
            self._active_workspace[user_id] = workspace_id
            if self._persistence:
                try:
                    self._persistence.save_active_workspace(user_id, workspace_id)
                except Exception:
                    pass
            return True

    def get_active_workspace(self, user_id: str) -> Workspace:
        from metatron.core.config import Settings

        default_id = Settings().default_workspace_id
        workspace_id = self._active_workspace.get(user_id)

        if workspace_id is None and self._persistence:
            try:
                workspace_id = self._persistence.load_active_workspace(user_id)
                if workspace_id:
                    self._active_workspace[user_id] = workspace_id
            except Exception:
                pass

        if workspace_id is None:
            workspace_id = default_id
        return self._workspaces.get(workspace_id, self._workspaces[default_id])

    def update_workspace_stats(self, workspace_id: str, stats: WorkspaceStats) -> None:
        self._stats[workspace_id] = stats
        if self._persistence:
            try:
                self._persistence.save_workspace_stats(workspace_id, stats)
            except Exception as e:
                logger.warning("workspace.stats.persist.failed", error=str(e))

    def get_workspace_stats(self, workspace_id: str) -> WorkspaceStats:
        if workspace_id in self._stats:
            return self._stats[workspace_id]
        if self._persistence:
            try:
                stats = self._persistence.load_workspace_stats(workspace_id)
                if stats:
                    self._stats[workspace_id] = stats
                    return stats
            except Exception:
                pass
        return WorkspaceStats()

    def workspace_exists(self, workspace_id: str) -> bool:
        from metatron.core.utils import normalize_workspace_id

        workspace_id = normalize_workspace_id(workspace_id)
        return workspace_id in self._workspaces

    def refresh_from_persistence(self) -> None:
        if self._persistence:
            self._load_from_persistence()
            self._ensure_default_workspace()

    # ------------------------------------------------------------------
    # Async lifecycle methods — ASOC workspace bootstrap (MTRNIX-352, T2)
    # ------------------------------------------------------------------

    def _get_async_lock(self) -> asyncio.Lock:
        """Lazy-initialize the async lock (must be created inside an event loop)."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def _require_bootstrap_deps(self) -> None:
        """Raise RuntimeError if ASOC lifecycle deps are not configured."""
        if self._bootstrap_store is None or self._bootstrap_runner is None:
            raise RuntimeError(
                "WorkspaceManager not configured for ASOC bootstrap — "
                "inject bootstrap_store and bootstrap_runner at construction."
            )

    async def bootstrap(
        self, workspace_id: str, source: str, config: dict[str, Any]
    ) -> BootstrapState:
        """Create or resume a workspace bootstrap.  Idempotent.

        State transitions:
        - absent → create PG workspace row, upsert bootstrap_state, schedule job → 202
        - bootstrapping / ready → return current state (idempotent)
        - failed → reset retry_count, re-launch job

        Requires ``bootstrap_store`` and ``bootstrap_runner`` to be injected.
        Note: ARCHIVED state removed per grooming 2026-05 (MTRNIX-370); use delete().
        """
        from metatron.core.exceptions import WorkspaceLifecycleError
        from metatron.workspaces.bootstrap.models import BootstrapStateEnum

        self._require_bootstrap_deps()
        assert self._bootstrap_store is not None
        assert self._bootstrap_runner is not None

        async with self._get_async_lock():
            existing = await self._bootstrap_store.get(workspace_id)

            if existing is None:
                # absent → provision + schedule
                await asyncio.to_thread(
                    self._sync_workspace_to_postgres,
                    Workspace(workspace_id=workspace_id, name=workspace_id),
                )
                state = await self._bootstrap_store.upsert_initial(workspace_id)
                await self._bootstrap_runner.schedule(workspace_id, source=source, config=config)
                return state

            if existing.state in (
                BootstrapStateEnum.BOOTSTRAPPING,
                BootstrapStateEnum.READY,
            ):
                return existing  # idempotent

            if existing.state == BootstrapStateEnum.FAILED:
                # Reset retry metadata before attempting the CAS so the new
                # bootstrapping attempt starts with a clean slate regardless of
                # which replica wins the race.
                await self._bootstrap_store.reset_retry(workspace_id)
                # Atomically transition FAILED → BOOTSTRAPPING.  If another
                # replica already won the race, skip scheduling to avoid double
                # job launch.
                won = await self._bootstrap_store.cas_set_state(
                    workspace_id,
                    from_state=BootstrapStateEnum.FAILED,
                    to_state=BootstrapStateEnum.BOOTSTRAPPING,
                )
                if won:
                    await self._bootstrap_runner.schedule(
                        workspace_id, source=source, config=config
                    )
                refreshed = await self._bootstrap_store.get(workspace_id)
                if refreshed is None:
                    raise WorkspaceLifecycleError(
                        f"Workspace '{workspace_id}' disappeared during"
                        " FAILED→BOOTSTRAPPING transition."
                    )
                return refreshed

            # defensive — unknown state string in DB
            raise WorkspaceLifecycleError(
                f"Workspace '{workspace_id}' has unknown state: {existing.state}"
            )

    async def delete(self, workspace_id: str) -> bool:
        """Idempotent workspace teardown.

        Best-effort cascade — each step is wrapped in suppress(Exception) so
        partial failures don't block subsequent steps.  Returns True if
        anything was deleted.
        """
        deleted_any = False

        # 1. Cancel in-flight bootstrap task.
        if self._bootstrap_runner:
            with contextlib.suppress(Exception):
                await self._bootstrap_runner.cancel(workspace_id)

        # 2. Drop Qdrant collection.
        with contextlib.suppress(Exception):
            from metatron.core.config import get_settings

            s = get_settings()
            client = AsyncQdrantClient(host=s.qdrant_host, port=s.qdrant_http_port)
            collection_name = get_collection_name(workspace_id)
            await client.delete_collection(collection_name)
            await client.close()
            logger.info("workspace.delete.qdrant_dropped", workspace_id=workspace_id)

        # 3. Clean Neo4j namespace.
        with contextlib.suppress(Exception):
            await asyncio.to_thread(delete_workspace_graph, workspace_id)
            logger.info("workspace.delete.neo4j_cleaned", workspace_id=workspace_id)

        # 4. Delete chat threads (cascades messages via FK).
        if self._chat_persistence:
            with contextlib.suppress(Exception):
                count = await self._chat_persistence.delete_threads_for_workspace(workspace_id)
                if count:
                    deleted_any = True

        # 5. Delete bootstrap_state row.
        if self._bootstrap_store:
            with contextlib.suppress(Exception):
                if await self._bootstrap_store.delete(workspace_id):
                    deleted_any = True

        # 6. Delete workspaces PG row + in-memory entry.
        with contextlib.suppress(Exception):
            from sqlalchemy import text as sa_text

            from metatron.storage.pg_connection import get_session

            with get_session() as session:
                result = session.execute(
                    sa_text("DELETE FROM workspaces WHERE id = :id RETURNING id"),
                    {"id": workspace_id},
                )
                if result.fetchone():
                    deleted_any = True
                session.commit()
            with self._lock:
                self._workspaces.pop(workspace_id, None)
            if self._persistence:
                with contextlib.suppress(Exception):
                    self._persistence.delete_workspace(workspace_id)

        logger.info(
            "workspace.delete.done",
            workspace_id=workspace_id,
            deleted_any=deleted_any,
        )
        return deleted_any


_workspace_manager: WorkspaceManager | None = None
_manager_lock = Lock()


def get_workspace_manager() -> WorkspaceManager:
    global _workspace_manager
    if _workspace_manager is None:
        with _manager_lock:
            if _workspace_manager is None:
                _workspace_manager = WorkspaceManager()
    return _workspace_manager
