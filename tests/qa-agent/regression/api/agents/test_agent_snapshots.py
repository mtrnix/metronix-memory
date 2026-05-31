"""Tests for creating and listing agent memory snapshots.

POST  /api/v1/agents/{agent_id}/snapshots — manual snapshot
GET   /api/v1/agents/{agent_id}/snapshots — list snapshots
"""

from __future__ import annotations

import uuid

import httpx

from .conftest import API, TIMEOUT


class TestCreateSnapshot:
    """POST /api/v1/agents/{agent_id}/snapshots — take a manual snapshot."""

    # type: positive, checks: [functional, mutation]
    def test_create_manual_snapshot(self, auth_headers, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/snapshots
        Scenario: editor takes a manual snapshot of agent memory (with label)
        Expected: 201, response contains snapshot id, agent_id, label, trigger=manual,
                  record_count, content_hash, size_bytes, storage_path, created_at
        Cleanup: snapshot is created and left as-is (read-only artifact)
        Source: src/metatron/api/routes/agents.py:create_agent_snapshot()
        """
        label = f"qa-test-snapshot-{uuid.uuid4().hex[:8]}"
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/snapshots",
            headers=auth_headers,
            json={"label": label},
            timeout=TIMEOUT,
        )
        assert r.status_code == 201, f"Snapshot creation failed: {r.text}"
        body = r.json()
        assert body["agent_id"] == existing_agent_id
        assert body["label"] == label
        assert body["trigger"] == "manual"
        assert "id" in body
        assert "workspace_id" in body
        assert "record_count" in body
        assert "content_hash" in body
        assert "size_bytes" in body
        assert "created_at" in body

    # type: positive, checks: [functional, mutation]
    def test_create_snapshot_without_label(self, auth_headers, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/snapshots
        Scenario: create snapshot without label (default empty string)
        Expected: 201, label is empty string
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/snapshots",
            headers=auth_headers,
            json={},
            timeout=TIMEOUT,
        )
        assert r.status_code == 201
        assert r.json()["label"] == ""

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: POST /api/v1/agents/nonexistent-id/snapshots
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.post(
            f"{API}/api/v1/agents/nonexistent-agent-id/snapshots",
            headers=auth_headers,
            json={"label": "test"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/snapshots
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/snapshots",
            json={"label": "test"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 401


class TestListSnapshots:
    """GET /api/v1/agents/{agent_id}/snapshots — list snapshots."""

    # type: positive, checks: [functional]
    def test_returns_snapshot_list(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/snapshots
        Scenario: viewer lists snapshots after creating one
        Expected: 200, snapshots list with count > 0 after creating a snapshot
        Source: src/metatron/api/routes/agents.py:list_agent_snapshots()
        """
        # Create a snapshot first
        httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/snapshots",
            headers=auth_headers,
            json={"label": "qa-test-list-check"},
            timeout=TIMEOUT,
        )

        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/snapshots",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert "snapshots" in body
        assert body["count"] >= 1
        assert "id" in body["snapshots"][0]

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: GET /api/v1/agents/nonexistent-id/snapshots
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.get(
            f"{API}/api/v1/agents/nonexistent-agent-id/snapshots",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/snapshots
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/snapshots",
            timeout=TIMEOUT,
        )
        assert r.status_code == 401
