"""Tests for knowledge graph visualization API endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from metronix.api.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


# --- overview ---


def test_overview_returns_nodes_and_edges(client):
    mock_data = {
        "nodes": [
            {
                "id": 1,
                "name": "Qdrant",
                "type": "Technology",
                "workspace_id": "ws_test",
                "connections": 5,
            },
            {
                "id": 2,
                "name": "Metronix",
                "type": "Project",
                "workspace_id": "ws_test",
                "connections": 3,
            },
        ],
        "edges": [
            {
                "source": 1,
                "target": 2,
                "type": "USED_IN",
                "valid_from": "2025-01-01",
                "valid_to": None,
            },
        ],
        "truncated": False,
    }
    with patch("metronix.storage.graph_ops.get_graph_overview", return_value=mock_data):
        resp = client.get("/api/v1/graph/overview?workspace_id=ws_test")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["nodes"][0]["name"] == "Qdrant"
    assert data["truncated"] is False
    assert "total_nodes" not in data


def test_overview_empty_graph(client):
    mock_data = {"nodes": [], "edges": [], "truncated": False}
    with patch("metronix.storage.graph_ops.get_graph_overview", return_value=mock_data):
        resp = client.get("/api/v1/graph/overview?workspace_id=ws_test")

    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []


def test_overview_requires_workspace_id(client):
    resp = client.get("/api/v1/graph/overview")
    assert resp.status_code == 422


def test_overview_memgraph_unavailable(client):
    with patch(
        "metronix.storage.graph_ops.get_graph_overview",
        side_effect=ServiceUnavailable("Connection refused"),
    ):
        resp = client.get("/api/v1/graph/overview?workspace_id=ws_test")

    assert resp.status_code == 502


def test_overview_limit_param(client):
    mock_data = {"nodes": [], "edges": [], "truncated": False}
    with patch("metronix.storage.graph_ops.get_graph_overview", return_value=mock_data) as m:
        resp = client.get("/api/v1/graph/overview?workspace_id=ws_test&limit=50")

    assert resp.status_code == 200
    m.assert_called_once_with("ws_test", 50, user_groups=None)


def test_overview_limit_validation(client):
    resp = client.get("/api/v1/graph/overview?workspace_id=ws_test&limit=0")
    assert resp.status_code == 422

    resp = client.get("/api/v1/graph/overview?workspace_id=ws_test&limit=999")
    assert resp.status_code == 422


# --- expand ---


def test_expand_returns_neighbors(client):
    mock_data = {
        "nodes": [
            {
                "id": 2,
                "name": "Metronix",
                "type": "Project",
                "workspace_id": "ws_test",
                "connections": 3,
            },
            {
                "id": 3,
                "name": "FastAPI",
                "type": "Technology",
                "workspace_id": "ws_test",
                "connections": 2,
            },
        ],
        "edges": [
            {"source": 1, "target": 2, "type": "USED_IN", "valid_from": None, "valid_to": None},
            {"source": 2, "target": 3, "type": "USES", "valid_from": None, "valid_to": None},
        ],
        "truncated": False,
    }
    with patch("metronix.storage.graph_ops.get_graph_expand", return_value=mock_data):
        resp = client.get("/api/v1/graph/expand/1?workspace_id=ws_test")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 2


def test_expand_requires_workspace_id(client):
    resp = client.get("/api/v1/graph/expand/1")
    assert resp.status_code == 422


def test_expand_depth_and_limit(client):
    mock_data = {"nodes": [], "edges": [], "truncated": False}
    with patch("metronix.storage.graph_ops.get_graph_expand", return_value=mock_data) as m:
        resp = client.get("/api/v1/graph/expand/1?workspace_id=ws_test&depth=3&limit=20")

    assert resp.status_code == 200
    m.assert_called_once_with(1, "ws_test", 3, 20, user_groups=None)


def test_expand_depth_validation(client):
    resp = client.get("/api/v1/graph/expand/1?workspace_id=ws_test&depth=0")
    assert resp.status_code == 422

    resp = client.get("/api/v1/graph/expand/1?workspace_id=ws_test&depth=5")
    assert resp.status_code == 422


def test_expand_memgraph_unavailable(client):
    with patch(
        "metronix.storage.graph_ops.get_graph_expand",
        side_effect=ServiceUnavailable("Connection refused"),
    ):
        resp = client.get("/api/v1/graph/expand/1?workspace_id=ws_test")

    assert resp.status_code == 502


# --- response schema ---


def test_response_schema_fields(client):
    mock_data = {
        "nodes": [
            {
                "id": 1,
                "name": "Alice",
                "type": "Person",
                "workspace_id": "ws_test",
                "connections": 1,
            }
        ],
        "edges": [
            {
                "source": 1,
                "target": 2,
                "type": "KNOWS",
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
            }
        ],
        "truncated": True,
    }
    with patch("metronix.storage.graph_ops.get_graph_overview", return_value=mock_data):
        resp = client.get("/api/v1/graph/overview?workspace_id=ws_test")

    data = resp.json()
    node = data["nodes"][0]
    assert set(node.keys()) == {"id", "name", "type", "workspace_id", "connections"}
    edge = data["edges"][0]
    assert set(edge.keys()) == {"source", "target", "type", "valid_from", "valid_to"}
    assert data["truncated"] is True
    assert "total_nodes" not in data
