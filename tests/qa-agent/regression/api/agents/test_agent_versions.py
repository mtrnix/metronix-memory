"""Tests for agent config versions — GET /api/v1/agents/{agent_id}/versions."""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT


class TestAgentVersions:
    """GET /api/v1/agents/{agent_id}/versions — config version history."""

    # type: positive, checks: [functional]
    def test_returns_version_history(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/versions
        Scenario: agent exists; at least version 1 exists after creation
        Expected: 200, versions list with at least 1 entry containing agent_id,
                  version, config, changed_by, changed_at
        Source: src/metatron/api/routes/agents.py:list_agent_versions()
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/versions",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert "versions" in body
        assert len(body["versions"]) >= 1
        v = body["versions"][0]
        assert v["agent_id"] == existing_agent_id
        assert v["version"] >= 1
        assert "config" in v
        assert "changed_by" in v
        assert "changed_at" in v
        assert "limit" in body
        assert "offset" in body
        assert "has_more" in body

    # type: positive, checks: [functional]
    def test_version_bumps_after_update(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/versions
        Scenario: update agent name, then check versions increased
        Expected: After update, at least 2 version entries exist
        """
        # Get version count before
        r1 = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/versions",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        before_count = r1.json()["count"]

        # Update
        httpx.put(
            f"{API}/api/v1/agents/{existing_agent_id}",
            headers=auth_headers,
            json={"name": f"qa-test-version-check-{existing_agent_id[:8]}"},
            timeout=TIMEOUT,
        )

        # Get version count after
        r2 = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/versions",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r2.status_code == 200
        after_count = r2.json()["count"]
        assert after_count > before_count, f"Versions not bumped: {before_count} -> {after_count}"

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: GET /api/v1/agents/nonexistent-id/versions
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.get(
            f"{API}/api/v1/agents/nonexistent-agent-id/versions",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/versions
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/versions",
            timeout=TIMEOUT,
        )
        assert r.status_code == 401

    # type: positive, checks: [functional, pagination]
    def test_respects_limit_and_offset(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/versions?limit=1
        Scenario: pagination on versions
        Expected: 200, at most 1 version returned, count <= limit
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/versions?limit=1",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["versions"]) <= 1
        assert body["limit"] == 1
