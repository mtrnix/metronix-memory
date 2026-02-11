"""Workspace persistence in Memgraph.

Migrated from PoC metatron/workspaces/persistence.py.
Stores workspace metadata in Memgraph for sync between environments.

# TODO: async migration
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, Optional, TypeVar

import structlog
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from metatron.workspaces.models import Workspace, WorkspaceStats

logger = structlog.get_logger()
T = TypeVar("T")


def with_retry(max_attempts: int = 3):
    """Retry decorator for database operations on connection errors."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self, *args, **kwargs) -> T:
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(self, *args, **kwargs)
                except (ServiceUnavailable, SessionExpired, BrokenPipeError, ConnectionError) as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        logger.warning("persistence.retry", func=func.__name__, attempt=attempt + 1, error=str(e))
                        self._close()
                except Exception as e:
                    if "broken pipe" in str(e).lower() or "connection" in str(e).lower():
                        last_error = e
                        if attempt < max_attempts - 1:
                            self._close()
                            continue
                    raise
            if last_error:
                raise last_error
            return None  # type: ignore[return-value]

        return wrapper

    return decorator


class MemgraphWorkspacePersistence:
    """Persist workspaces to Memgraph graph database."""

    def __init__(self) -> None:
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            from metatron.core.config import Settings
            settings = Settings()
            self._driver = GraphDatabase.driver(
                settings.memgraph_uri,
                auth=(settings.memgraph_user, settings.memgraph_password) if settings.memgraph_user else None,
            )
        return self._driver

    def _close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None

    @with_retry()
    def save_workspace(self, workspace: Workspace) -> None:
        driver = self._get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (w:Workspace {workspace_id: $workspace_id})
                SET w.name = $name, w.description = $description,
                    w.created_at = $created_at, w.user_id = $user_id,
                    w.is_active = $is_active, w.config = $config,
                    w.updated_at = $updated_at
                """,
                {
                    "workspace_id": workspace.workspace_id,
                    "name": workspace.name,
                    "description": workspace.description or "",
                    "created_at": workspace.created_at,
                    "user_id": workspace.user_id,
                    "is_active": workspace.is_active,
                    "config": json.dumps(workspace.config or {}),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    @with_retry()
    def load_all_workspaces(self) -> list[Workspace]:
        driver = self._get_driver()
        workspaces = []
        with driver.session() as session:
            result = session.run("MATCH (w:Workspace) RETURN w")
            for record in result:
                ws = self._node_to_workspace(record["w"])
                if ws:
                    workspaces.append(ws)
        return workspaces

    @with_retry()
    def delete_workspace(self, workspace_id: str) -> bool:
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(
                "MATCH (w:Workspace {workspace_id: $wid}) DELETE w RETURN count(w) as deleted",
                {"wid": workspace_id},
            )
            record = result.single()
            return record["deleted"] > 0 if record else False

    @with_retry()
    def save_active_workspace(self, user_id: str, workspace_id: str) -> None:
        driver = self._get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (s:WorkspaceSetting {user_id: $user_id})
                SET s.active_workspace_id = $wid, s.updated_at = $updated_at
                """,
                {"user_id": user_id, "wid": workspace_id, "updated_at": datetime.now(timezone.utc).isoformat()},
            )

    @with_retry()
    def load_active_workspace(self, user_id: str) -> str | None:
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(
                "MATCH (s:WorkspaceSetting {user_id: $uid}) RETURN s.active_workspace_id as wid",
                {"uid": user_id},
            )
            record = result.single()
            return record["wid"] if record else None

    @with_retry()
    def save_workspace_stats(self, workspace_id: str, stats: WorkspaceStats) -> None:
        driver = self._get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (s:WorkspaceStats {workspace_id: $wid})
                SET s.document_count = $dc, s.entity_count = $ec,
                    s.jira_issue_count = $jic, s.total_chunks = $tc,
                    s.last_upload_time = $lut, s.updated_at = $updated_at
                """,
                {
                    "wid": workspace_id,
                    "dc": stats.document_count,
                    "ec": stats.entity_count,
                    "jic": stats.jira_issue_count,
                    "tc": stats.total_chunks,
                    "lut": stats.last_upload_time,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    @with_retry()
    def load_workspace_stats(self, workspace_id: str) -> WorkspaceStats | None:
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(
                "MATCH (s:WorkspaceStats {workspace_id: $wid}) RETURN s",
                {"wid": workspace_id},
            )
            record = result.single()
            if record:
                node = record["s"]
                return WorkspaceStats(
                    document_count=node.get("document_count", 0),
                    entity_count=node.get("entity_count", 0),
                    jira_issue_count=node.get("jira_issue_count", 0),
                    total_chunks=node.get("total_chunks", 0),
                    last_upload_time=node.get("last_upload_time"),
                )
            return None

    @with_retry()
    def load_all_workspace_stats(self) -> dict[str, WorkspaceStats]:
        driver = self._get_driver()
        stats_dict: dict[str, WorkspaceStats] = {}
        with driver.session() as session:
            result = session.run("MATCH (s:WorkspaceStats) RETURN s")
            for record in result:
                node = record["s"]
                wid = node.get("workspace_id")
                if wid:
                    stats_dict[wid] = WorkspaceStats(
                        document_count=node.get("document_count", 0),
                        entity_count=node.get("entity_count", 0),
                        jira_issue_count=node.get("jira_issue_count", 0),
                        total_chunks=node.get("total_chunks", 0),
                        last_upload_time=node.get("last_upload_time"),
                    )
        return stats_dict

    def _node_to_workspace(self, node) -> Workspace | None:
        try:
            config_str = node.get("config", "{}")
            config = json.loads(config_str) if config_str else {}
            return Workspace(
                workspace_id=node["workspace_id"],
                name=node.get("name", ""),
                description=node.get("description") or None,
                created_at=node.get("created_at"),
                user_id=node.get("user_id", "user"),
                is_active=node.get("is_active", True),
                config=config,
            )
        except Exception as e:
            logger.error("workspace.node.convert.failed", error=str(e))
            return None


_persistence: Optional[MemgraphWorkspacePersistence] = None


def get_workspace_persistence() -> MemgraphWorkspacePersistence:
    global _persistence
    if _persistence is None:
        _persistence = MemgraphWorkspacePersistence()
    return _persistence
