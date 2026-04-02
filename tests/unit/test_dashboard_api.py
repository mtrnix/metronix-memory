"""Tests for dashboard API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.api.routes.dashboard.overview import get_valid_workspace
from metatron.workspaces.models import Workspace


@pytest.fixture
def mock_workspace():
    """Create mock workspace."""
    return Workspace(workspace_id="test-ws", name="Test Workspace")


@pytest.fixture
def client(mock_workspace):
    """Create test client with mocked workspace dependency."""
    app = create_app()

    # Override workspace dependency for all tests
    app.dependency_overrides[get_valid_workspace] = lambda: mock_workspace

    yield TestClient(app)

    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_override():
    """Create test client without workspace override for testing 404/422 cases."""
    app = create_app()
    return TestClient(app)


def test_overview_kpi_success(client):
    """Test successful overview KPI retrieval."""
    with patch("metatron.storage.dashboard_queries.get_overview_stats") as mock_stats:
        # Mock overview stats
        mock_stats.return_value = {
            "documents": 12483,
            "jira_issues": 841,
            "active_connectors": 3,
            "last_upload": datetime(2026, 3, 2, 9, 12, 0, tzinfo=UTC),
        }

        response = client.get("/api/v1/dashboard/overview?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 12483
        assert data["jira_issues"] == 841
        assert data["active_connectors"] == 3
        assert data["last_upload"] == "2026-03-02T09:12:00Z"


def test_overview_kpi_workspace_not_found(client_no_override):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.workspaces.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None

        response = client_no_override.get("/api/v1/dashboard/overview?workspace_id=nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_overview_kpi_postgres_error_graceful_degradation(client):
    """Test graceful degradation when PostgreSQL fails."""
    with patch("metatron.storage.dashboard_queries.get_overview_stats") as mock_stats:
        # Mock overview stats with graceful degradation (0 for failed connectors)
        mock_stats.return_value = {
            "documents": 100,
            "jira_issues": 10,
            "active_connectors": 0,  # Graceful degradation
            "last_upload": datetime(2026, 3, 2, 9, 12, 0, tzinfo=UTC),
        }

        response = client.get("/api/v1/dashboard/overview?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 100
        assert data["jira_issues"] == 10
        assert data["active_connectors"] == 0  # Graceful degradation
        assert data["last_upload"] == "2026-03-02T09:12:00Z"


def test_overview_kpi_null_last_upload(client):
    """Test handling of null last_upload_time."""
    with patch("metatron.storage.dashboard_queries.get_overview_stats") as mock_stats:
        # Mock overview stats with null last_upload
        mock_stats.return_value = {
            "documents": 0,
            "jira_issues": 0,
            "active_connectors": 0,
            "last_upload": None,  # No uploads yet
        }

        response = client.get("/api/v1/dashboard/overview?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 0
        assert data["jira_issues"] == 0
        assert data["active_connectors"] == 0
        assert data["last_upload"] is None


def test_overview_kpi_missing_workspace_id(client_no_override):
    """Test 422 when workspace_id parameter is missing."""
    response = client_no_override.get("/api/v1/dashboard/overview")

    assert response.status_code == 422  # FastAPI validation error


def test_sync_history_success(client):
    """Test successful sync history retrieval."""
    with patch("metatron.storage.dashboard_queries.get_sync_history_data") as mock_history:
        # Mock sync history
        from metatron.api.routes.dashboard.sync import SyncHistoryItem

        mock_history.return_value = [
            SyncHistoryItem(
                id="sync_1",
                source="confluence",
                title="Confluence Sync",
                started=datetime(2026, 3, 2, 8, 45, 12, tzinfo=UTC),
                duration_ms=1240.5,
                records=18,
                status="success",
            ),
            SyncHistoryItem(
                id="sync_2",
                source="jira",
                title="Jira Sync",
                started=datetime(2026, 3, 2, 7, 30, 0, tzinfo=UTC),
                duration_ms=890.2,
                records=12,
                status="partial",
            ),
        ]

        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["items"][0]["id"] == "sync_1"
        assert data["items"][0]["source"] == "confluence"
        assert data["items"][0]["title"] == "Confluence Sync"
        assert data["items"][0]["duration_ms"] == 1240.5
        assert data["items"][0]["records"] == 18
        assert data["items"][0]["status"] == "success"


def test_sync_history_workspace_not_found(client_no_override):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.workspaces.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None

        response = client_no_override.get(
            "/api/v1/dashboard/sync-history?workspace_id=nonexistent"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_sync_history_empty_result(client):
    """Test empty sync history."""
    with patch("metatron.storage.dashboard_queries.get_sync_history_data") as mock_history:
        # Mock empty history
        mock_history.return_value = []

        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []


def test_sync_history_custom_limit(client):
    """Test sync history with custom limit."""
    with patch("metatron.storage.dashboard_queries.get_sync_history_data") as mock_history:
        # Mock sync history
        from metatron.api.routes.dashboard.sync import SyncHistoryItem

        mock_history.return_value = [
            SyncHistoryItem(
                id=f"sync_{i}",
                source="confluence",
                title=f"Sync {i}",
                started=datetime(2026, 3, 2, 8, 0, 0, tzinfo=UTC),
                duration_ms=1000.0,
                records=10,
                status="success",
            )
            for i in range(5)
        ]

        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5
        # Verify limit was passed to the function
        mock_history.assert_called_once_with("test-ws", 5)


def test_sync_history_limit_validation(client):
    """Test limit parameter validation."""
    # Test limit too large
    response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=101")
    assert response.status_code == 422

    # Test limit too small
    response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=0")
    assert response.status_code == 422


def test_ingestion_errors_success(client):
    """Test successful ingestion errors retrieval."""
    with patch("metatron.storage.dashboard_queries.get_ingestion_errors_data") as mock_errors:
        # Mock ingestion errors
        from metatron.api.routes.dashboard.sync import IngestionErrorItem

        mock_errors.return_value = (
            14,  # total count
            [
                IngestionErrorItem(
                    source="confluence",
                    record="page_id:12345 — Migration Guide",
                    error="Qdrant timeout after 30s",
                    time=datetime(2026, 3, 2, 7, 30, 0, tzinfo=UTC),
                    severity="warning",
                ),
                IngestionErrorItem(
                    source="jira",
                    record="Jira Sync",
                    error="Connection refused",
                    time=datetime(2026, 3, 2, 6, 15, 0, tzinfo=UTC),
                    severity="critical",
                ),
            ],
        )

        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=20")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 14
        assert len(data["items"]) == 2
        assert data["items"][0]["source"] == "confluence"
        assert data["items"][0]["record"] == "page_id:12345 — Migration Guide"
        assert data["items"][0]["error"] == "Qdrant timeout after 30s"
        assert data["items"][0]["severity"] == "warning"
        assert data["items"][1]["severity"] == "critical"


def test_ingestion_errors_workspace_not_found(client_no_override):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.workspaces.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None

        response = client_no_override.get(
            "/api/v1/dashboard/ingestion-errors?workspace_id=nonexistent"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_ingestion_errors_empty_result(client):
    """Test empty ingestion errors (no failures)."""
    with patch("metatron.storage.dashboard_queries.get_ingestion_errors_data") as mock_errors:
        # Mock empty errors
        mock_errors.return_value = (0, [])

        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


def test_ingestion_errors_custom_limit(client):
    """Test ingestion errors with custom limit."""
    with patch("metatron.storage.dashboard_queries.get_ingestion_errors_data") as mock_errors:
        # Mock ingestion errors
        from metatron.api.routes.dashboard.sync import IngestionErrorItem

        mock_errors.return_value = (
            50,  # total count
            [
                IngestionErrorItem(
                    source="confluence",
                    record=f"Error {i}",
                    error="Test error",
                    time=datetime(2026, 3, 2, 8, 0, 0, tzinfo=UTC),
                    severity="warning",
                )
                for i in range(10)
            ],
        )

        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 50
        assert len(data["items"]) == 10
        # Verify limit was passed to the function
        mock_errors.assert_called_once_with("test-ws", 10)


def test_ingestion_errors_limit_validation(client):
    """Test limit parameter validation."""
    # Test limit too large
    response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=101")
    assert response.status_code == 422

    # Test limit too small
    response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=0")
    assert response.status_code == 422


def test_ingestion_errors_graceful_degradation(client):
    """Test graceful degradation when PostgreSQL fails."""
    with patch("metatron.storage.dashboard_queries.get_ingestion_errors_data") as mock_errors:
        # Mock PostgreSQL error - function returns empty result
        mock_errors.return_value = (0, [])

        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


def test_query_trend_success(client):
    """Test successful query trend retrieval."""
    with patch("metatron.storage.dashboard_queries.get_query_trend_data") as mock_trend:
        # Mock query trend data
        mock_trend.return_value = (
            ["2026-02-01", "2026-02-02", "2026-02-03"],
            [124, 98, 156],
        )

        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=30")

        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == ["2026-02-01", "2026-02-02", "2026-02-03"]
        assert data["values"] == [124, 98, 156]


def test_query_trend_workspace_not_found(client_no_override):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.workspaces.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None

        response = client_no_override.get("/api/v1/dashboard/query-trend?workspace_id=nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_query_trend_empty_result(client):
    """Test empty query trend (no queries yet)."""
    with patch("metatron.storage.dashboard_queries.get_query_trend_data") as mock_trend:
        # Mock empty trend (all zeros)
        mock_trend.return_value = (
            ["2026-03-01", "2026-03-02", "2026-03-03"],
            [0, 0, 0],
        )

        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=3")

        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == ["2026-03-01", "2026-03-02", "2026-03-03"]
        assert data["values"] == [0, 0, 0]


def test_query_trend_custom_days(client):
    """Test query trend with custom days parameter."""
    with patch("metatron.storage.dashboard_queries.get_query_trend_data") as mock_trend:
        # Mock trend data for 7 days
        mock_trend.return_value = (
            [f"2026-02-{i:02d}" for i in range(1, 8)],
            [10, 20, 15, 30, 25, 18, 22],
        )

        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=7")

        assert response.status_code == 200
        data = response.json()
        assert len(data["labels"]) == 7
        assert len(data["values"]) == 7
        # Verify days parameter was passed to the function
        mock_trend.assert_called_once_with("test-ws", 7)


def test_query_trend_default_days(client):
    """Test query trend with default days parameter (30)."""
    with patch("metatron.storage.dashboard_queries.get_query_trend_data") as mock_trend:
        # Mock trend data
        mock_trend.return_value = ([], [])

        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws")

        assert response.status_code == 200
        # Verify default days=30 was used
        mock_trend.assert_called_once_with("test-ws", 30)


def test_query_trend_days_validation(client):
    """Test days parameter validation."""
    # Test days too large
    response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=366")
    assert response.status_code == 422

    # Test days too small
    response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=0")
    assert response.status_code == 422


def test_query_trend_graceful_degradation(client):
    """Test graceful degradation when PostgreSQL fails."""
    with patch("metatron.storage.dashboard_queries.get_query_trend_data") as mock_trend:
        # Mock PostgreSQL error - function returns empty arrays
        mock_trend.return_value = ([], [])

        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == []
        assert data["values"] == []


def test_graph_stats_success(client):
    """Test successful graph stats retrieval."""
    with patch("metatron.storage.dashboard_queries.get_graph_stats_data") as mock_stats:
        # Mock graph stats
        mock_stats.return_value = {
            "total_nodes": 89200,
            "total_edges": 142800,
            "orphan_nodes": 2,
            "orphan_list": [
                {"id": "node_123", "label": "Entity", "name": "Deprecated API v1"},
                {"id": "node_456", "label": "Document", "name": "Old Doc"},
            ],
            "raw_documents": 24831,
            "chunks": 412000,
        }

        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 89200
        assert data["total_edges"] == 142800
        assert data["orphan_nodes"] == 2
        assert len(data["orphan_list"]) == 2
        assert data["orphan_list"][0]["id"] == "node_123"
        assert data["orphan_list"][0]["label"] == "Entity"
        assert data["orphan_list"][0]["name"] == "Deprecated API v1"
        assert data["lineage"]["raw_documents"] == 24831
        assert data["lineage"]["chunks"] == 412000
        assert data["lineage"]["graph_nodes"] == 89200


def test_graph_stats_workspace_not_found(client_no_override):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.workspaces.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None

        response = client_no_override.get("/api/v1/dashboard/graph-stats?workspace_id=nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_graph_stats_empty_graph(client):
    """Test graph stats with empty graph."""
    with patch("metatron.storage.dashboard_queries.get_graph_stats_data") as mock_stats:
        # Mock empty graph
        mock_stats.return_value = {
            "total_nodes": 0,
            "total_edges": 0,
            "orphan_nodes": 0,
            "orphan_list": [],
            "raw_documents": 0,
            "chunks": 0,
        }

        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 0
        assert data["total_edges"] == 0
        assert data["orphan_nodes"] == 0
        assert data["orphan_list"] == []
        assert data["lineage"]["raw_documents"] == 0
        assert data["lineage"]["chunks"] == 0
        assert data["lineage"]["graph_nodes"] == 0


def test_graph_stats_no_orphans(client):
    """Test graph stats with no orphan nodes."""
    with patch("metatron.storage.dashboard_queries.get_graph_stats_data") as mock_stats:
        # Mock graph with no orphans
        mock_stats.return_value = {
            "total_nodes": 1000,
            "total_edges": 2500,
            "orphan_nodes": 0,
            "orphan_list": [],
            "raw_documents": 100,
            "chunks": 5000,
        }

        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 1000
        assert data["total_edges"] == 2500
        assert data["orphan_nodes"] == 0
        assert data["orphan_list"] == []


def test_graph_stats_graceful_degradation(client):
    """Test graceful degradation when Memgraph/Qdrant fails."""
    with patch("metatron.storage.dashboard_queries.get_graph_stats_data") as mock_stats:
        # Mock error - function returns zeros
        mock_stats.return_value = {
            "total_nodes": 0,
            "total_edges": 0,
            "orphan_nodes": 0,
            "orphan_list": [],
            "raw_documents": 0,
            "chunks": 0,
        }

        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")

        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 0
        assert data["total_edges"] == 0
