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
    
    # Get jira_issues count from Memgraph
    try:
        from metatron.storage.memgraph import get_memgraph_driver
        driver = get_memgraph_driver()
        with driver.session() as session:
            cypher_result = session.run(
                "MATCH (j:JiraIssue {workspace_id: $wid}) RETURN count(j) AS cnt",
                {"wid": workspace_id},
            )
            record = cypher_result.single()
            if record:
                result["jira_issues"] = record["cnt"]
    except Exception as e:
        logger.warning(
            "dashboard.overview.memgraph.error",
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


def get_sync_history_data(workspace_id: str, limit: int) -> list[dict]:
    """Get sync history for a workspace.
    
    Args:
        workspace_id: Workspace ID to query.
        limit: Maximum number of records to return.
        
    Returns:
        List of sync history items.
    """
    try:
        with get_session() as session:
            result = session.execute(
                select(SyncLogRow)
                .where(SyncLogRow.workspace_id == workspace_id)
                .order_by(SyncLogRow.created_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            
            items = []
            for row in rows:
                items.append({
                    "id": row.id,
                    "source": row.connector_type,
                    "title": row.source_title or f"{row.connector_type.capitalize()} Sync",
                    "started": row.created_at,
                    "duration_ms": row.duration_ms,
                    "records": row.qdrant_chunks,
                    "status": row.status,
                })
            return items
    except Exception as e:
        logger.warning(
            "dashboard.sync_history.error",
            workspace_id=workspace_id,
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
                
                items.append({
                    "source": row.connector_type,
                    "record": record,
                    "error": error_msg,
                    "time": row.created_at,
                    "severity": severity,
                })
            
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
    
    # Get graph stats from Memgraph
    try:
        from metatron.storage.memgraph import get_memgraph_driver
        
        driver = get_memgraph_driver()
        with driver.session() as session:
            # Count total nodes
            node_result = session.run(
                "MATCH (n {workspace_id: $wid}) RETURN count(n) AS cnt",
                {"wid": workspace_id},
            )
            node_record = node_result.single()
            if node_record:
                result["total_nodes"] = node_record["cnt"]
            
            # Count total edges (directed)
            edge_result = session.run(
                "MATCH (a {workspace_id: $wid})-[r]->(b {workspace_id: $wid}) RETURN count(r) AS cnt",
                {"wid": workspace_id},
            )
            edge_record = edge_result.single()
            if edge_record:
                result["total_edges"] = edge_record["cnt"]
            
            # Find orphan nodes (nodes without any relationships)
            orphan_result = session.run(
                """
                MATCH (n {workspace_id: $wid})
                WHERE NOT (n)--()
                RETURN elementId(n) AS id, labels(n)[0] AS label,
                       COALESCE(n.name, n.title, n.id, 'Unknown') AS name
                LIMIT $limit
                """,
                {"wid": workspace_id, "limit": MAX_ORPHAN_NODES_LIMIT},
            )
            orphan_list = []
            for record in orphan_result:
                orphan_list.append({
                    "id": record["id"],
                    "label": record["label"] or "Node",
                    "name": record["name"],
                })
            result["orphan_nodes"] = len(orphan_list)
            result["orphan_list"] = orphan_list
    
    except Exception as e:
        logger.warning(
            "dashboard.graph_stats.memgraph.error",
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
