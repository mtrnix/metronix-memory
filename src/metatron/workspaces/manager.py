"""Workspace manager — handles workspace CRUD and activation.

Migrated from PoC metatron/workspaces/manager.py.
Supports both in-memory and persistent storage (Memgraph).

# TODO: async migration
"""

from __future__ import annotations

import uuid
from threading import Lock
from typing import Optional

import structlog

from metatron.workspaces.models import Workspace, WorkspaceStats

logger = structlog.get_logger()


class WorkspaceManager:
    """Manager for workspace operations.

    Supports both in-memory and persistent storage (Memgraph).
    """

    def __init__(self, use_persistence: bool = True) -> None:
        self._workspaces: dict[str, Workspace] = {}
        self._active_workspace: dict[str, str] = {}
        self._lock = Lock()
        self._stats: dict[str, WorkspaceStats] = {}
        self._persistence = None
        self._use_persistence = False

        if use_persistence:
            try:
                from metatron.core.config import Settings
                settings = Settings()
                if settings.workspace_persistence == "memgraph":
                    from metatron.workspaces.persistence import get_workspace_persistence
                    self._persistence = get_workspace_persistence()
                    self._use_persistence = True
                    self._load_from_persistence()
                    logger.info("workspace.persistence.enabled", backend="memgraph")
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
            from metatron.storage.pg_connection import get_session
            from sqlalchemy import text
            
            with get_session() as session:
                # Check if workspace exists
                result = session.execute(
                    text("SELECT id FROM workspaces WHERE id = :id"),
                    {"id": workspace.workspace_id}
                ).fetchone()
                
                if result:
                    # Update existing
                    session.execute(
                        text("UPDATE workspaces SET name = :name, slug = :slug WHERE id = :id"),
                        {
                            "id": workspace.workspace_id,
                            "name": workspace.name,
                            "slug": workspace.workspace_id.lower(),
                        }
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
                        }
                    )
                
                session.commit()
                logger.info("workspace.postgres.synced", workspace_id=workspace.workspace_id)
        except Exception as e:
            logger.warning("workspace.postgres.sync.failed", workspace_id=workspace.workspace_id, error=str(e))

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
                w for w in workspaces
                if w.user_id == user_id or w.workspace_id == default_id
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


_workspace_manager: Optional[WorkspaceManager] = None
_manager_lock = Lock()


def get_workspace_manager() -> WorkspaceManager:
    global _workspace_manager
    if _workspace_manager is None:
        with _manager_lock:
            if _workspace_manager is None:
                _workspace_manager = WorkspaceManager()
    return _workspace_manager
