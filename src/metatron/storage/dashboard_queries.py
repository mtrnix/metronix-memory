"""Dashboard database queries - storage layer for dashboard endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import cast, func, select
from sqlalchemy.types import Date

from metatron.storage.pg_connection import get_session
from metatron.storage.pg_models import ConnectionRow, QueryTraceRow, SyncLogRow

logger = structlog.get_logger()

MAX_ORPHAN_NODES_LIMIT = 100


def get_overview_stats(workspace_id: str) -> dict:
    """Get overview KPI statistics.

    Args:
        workspace_id: Workspace ID to query.

    Returns:
        Dict with documents, jira_issues, active_connectors, last_upload.
    """
    result = {
        "documents": 0,
        "jira_issues": 0,
        "active_connectors": 0,
        "last_upload": None,
    }

    # Get document count from Qdrant
    try:
        from metatron.storage.qdrant import get_hybrid_store

        store = get_hybrid_store(workspace_id)
        qdrant_stats = store.get_stats()
        result["documents"] = qdrant_stats.get("file_count", 0)
    except Exception as e:
        logger.warning(
            "dashboard.overview.qdrant.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    # Get jira_issues count from Neo4j
    try:
        from metatron.storage.neo4j_graph import get_graph_driver

        driver = get_graph_driver()
        with driver.session() as session:
            cypher_result = session.run(
                "MATCH (j:JiraIssue) WHERE j.workspace_id = $ws RETURN count(j)",
                {"ws": workspace_id},
            )
            record = cypher_result.single()
            if record:
                result["jira_issues"] = record[0]
    except Exception as e:
        logger.warning(
            "dashboard.overview.neo4j.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    # Count active connectors from PostgreSQL
    try:
        with get_session() as session:
            count_result = session.execute(
                select(func.count(ConnectionRow.id)).where(
                    ConnectionRow.workspace_id == workspace_id,
                    ConnectionRow.status == "active",
                )
            )
            count = count_result.scalar()
            result["active_connectors"] = count or 0
    except Exception as e:
        logger.warning(
            "dashboard.overview.connections.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    # Get last_upload from workspace stats
    try:
        from metatron.workspaces import get_workspace_manager

        manager = get_workspace_manager()
        stats = manager.get_workspace_stats(workspace_id)
        result["last_upload"] = stats.last_upload_time if stats else None
    except Exception as e:
        logger.warning(
            "dashboard.overview.workspace_stats.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    return result


def get_sync_history_data(
    workspace_id: str,
    limit: int,
    connection_id: str | None = None,
) -> list[dict]:
    """Get sync history for a workspace, optionally filtered by connection.

    Args:
        workspace_id: Workspace ID to query.
        limit: Maximum number of records to return.
        connection_id: Optional connection ID filter.

    Returns:
        List of sync history items with full sync-log fields.
    """
    try:
        with get_session() as session:
            stmt = (
                select(SyncLogRow)
                .where(SyncLogRow.workspace_id == workspace_id)
                .order_by(SyncLogRow.created_at.desc())
                .limit(limit)
            )
            if connection_id is not None:
                stmt = stmt.where(SyncLogRow.connection_id == connection_id)

            result = session.execute(stmt)
            rows = result.scalars().all()

            items: list[dict] = []
            for row in rows:
                items.append(
                    {
                        "id": row.id,
                        "connection_id": row.connection_id,
                        "connector_type": row.connector_type,
                        "title": row.source_title or f"{row.connector_type.capitalize()} Sync",
                        "started": row.created_at,
                        "duration_ms": row.duration_ms,
                        "documents_fetched": row.documents_fetched,
                        "documents_new": row.documents_new,
                        "documents_updated": row.documents_updated,
                        "documents_skipped": row.documents_skipped,
                        "qdrant_chunks": row.qdrant_chunks,
                        "errors": row.errors or [],
                        "status": row.status,
                    }
                )
            return items
    except Exception as e:
        logger.warning(
            "dashboard.sync_history.error",
            workspace_id=workspace_id,
            connection_id=connection_id,
            error=str(e),
        )
        return []


def get_ingestion_errors_data(workspace_id: str, limit: int) -> tuple[int, list[dict]]:
    """Get ingestion errors for a workspace.

    Args:
        workspace_id: Workspace ID to query.
        limit: Maximum number of error records to return.

    Returns:
        Tuple of (total_count, error_items).
    """
    try:
        with get_session() as session:
            # Count total errors
            count_result = session.execute(
                select(func.count(SyncLogRow.id)).where(
                    SyncLogRow.workspace_id == workspace_id,
                    SyncLogRow.status != "success",
                )
            )
            total = count_result.scalar() or 0

            # Get error records
            result = session.execute(
                select(SyncLogRow)
                .where(
                    SyncLogRow.workspace_id == workspace_id,
                    SyncLogRow.status != "success",
                )
                .order_by(SyncLogRow.created_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()

            items = []
            for row in rows:
                # Determine severity based on status
                severity = "warning"
                if row.status == "failed":
                    severity = "critical"
                elif row.status == "partial":
                    severity = "warning"

                # Format record identifier
                record = row.source_title or f"{row.connector_type.capitalize()} Sync"

                # Extract error message from errors JSONB field
                error_msg = "Unknown error"
                if row.errors and isinstance(row.errors, list) and len(row.errors) > 0:
                    # Take first error from array
                    first_error = row.errors[0]
                    if isinstance(first_error, dict):
                        error_msg = first_error.get("message", str(first_error))
                    else:
                        error_msg = str(first_error)
                    # Truncate to 200 chars
                    if len(error_msg) > 200:
                        error_msg = error_msg[:197] + "..."

                items.append(
                    {
                        "source": row.connector_type,
                        "record": record,
                        "error": error_msg,
                        "time": row.created_at,
                        "severity": severity,
                    }
                )

            return total, items
    except Exception as e:
        logger.warning(
            "dashboard.ingestion_errors.error",
            workspace_id=workspace_id,
            error=str(e),
        )
        return 0, []


def get_query_trend_data(workspace_id: str, days: int) -> tuple[list[str], list[int]]:
    """Get query trend for a workspace.

    Args:
        workspace_id: Workspace ID to query.
        days: Number of days to look back.

    Returns:
        Tuple of (date_labels, query_counts).
    """
    try:
        with get_session() as session:
            # Calculate date range
            end_date = datetime.now(UTC).date()
            start_date = end_date - timedelta(days=days - 1)

            # Query: group by date, count queries
            result = session.execute(
                select(
                    cast(QueryTraceRow.created_at, Date).label("date"),
                    func.count(QueryTraceRow.id).label("count"),
                )
                .where(
                    QueryTraceRow.workspace_id == workspace_id,
                    QueryTraceRow.created_at >= start_date,
                )
                .group_by(cast(QueryTraceRow.created_at, Date))
                .order_by(cast(QueryTraceRow.created_at, Date))
            )
            rows = result.all()

            # Build date -> count mapping
            date_counts = {row.date: row.count for row in rows}

            # Generate complete date range (fill missing dates with 0)
            labels = []
            values = []
            current_date = start_date
            while current_date <= end_date:
                labels.append(current_date.isoformat())
                values.append(date_counts.get(current_date, 0))
                current_date += timedelta(days=1)

            return labels, values
    except Exception as e:
        logger.warning(
            "dashboard.query_trend.error",
            workspace_id=workspace_id,
            error=str(e),
        )
        return [], []


def get_graph_stats_data(workspace_id: str) -> dict:
    """Get knowledge graph statistics.

    Args:
        workspace_id: Workspace ID to query.

    Returns:
        Dictionary with graph statistics.
    """
    result = {
        "total_nodes": 0,
        "total_edges": 0,
        "orphan_nodes": 0,
        "orphan_list": [],
        "raw_documents": 0,
        "chunks": 0,
    }

    # Get graph stats from Neo4j
    try:
        from metatron.storage.neo4j_graph import get_graph_driver

        driver = get_graph_driver()
        with driver.session() as session:
            node_result = session.run(
                "MATCH (n) WHERE n.workspace_id = $ws RETURN count(n)",
                {"ws": workspace_id},
            )
            node_record = node_result.single()
            if node_record:
                result["total_nodes"] = node_record[0]

            edge_result = session.run(
                "MATCH (a)-[r]->(b) WHERE a.workspace_id = $ws"
                " AND b.workspace_id = $ws RETURN count(r)",
                {"ws": workspace_id},
            )
            edge_record = edge_result.single()
            if edge_record:
                result["total_edges"] = edge_record[0]

            orphan_result = session.run(
                "MATCH (n) WHERE n.workspace_id = $ws AND NOT (n)--() "
                "RETURN elementId(n) AS id, n.name AS name,"
                " labels(n) AS labels LIMIT 100",
                {"ws": workspace_id},
            )
            orphan_records = list(orphan_result)
            result["orphan_nodes"] = len(orphan_records)
            result["orphan_list"] = [
                {
                    "id": r["id"],
                    "label": r["labels"][0] if r["labels"] else "Unknown",
                    "name": r["name"] or "unnamed",
                }
                for r in orphan_records
            ]

    except Exception as e:
        logger.warning(
            "dashboard.graph_stats.neo4j.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    # Get document and chunk counts from Qdrant
    try:
        from metatron.storage.qdrant import get_hybrid_store

        store = get_hybrid_store(workspace_id)
        qdrant_stats = store.get_stats()
        result["raw_documents"] = qdrant_stats.get("file_count", 0)
        result["chunks"] = qdrant_stats.get("chunk_count", 0)
    except Exception as e:
        logger.warning(
            "dashboard.graph_stats.qdrant.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    return result
