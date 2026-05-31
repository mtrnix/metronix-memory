"""Tests for getting a single agent — GET /api/v1/agents/{agent_id}."""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT


class TestGetAgent:
    """GET /api/v1/agents/{agent_id} — fetch a single agent."""

    # type: positive, checks: [functional, auth]
    def test_returns_agent_by_id(self, auth_headers, created_agent):
        """Endpoint: GET /api/v1/agents/{agent_id}
        Scenario: authenticated viewer fetches an existing agent
        Expected: 200, response contains id, name, status, model, workspace_id,
                  config_version, current_config, created_by, created_at, updated_at
        Source: src/metatron/api/routes/agents.py:get_agent()
        """
        agent_id = created_agent["id"]
        r = httpx.get(f"{API}/api/v1/agents/{agent_id}", headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == agent_id
        assert body["name"] == created_agent["name"]
        assert body["status"] == "stopped"
        assert body["workspace_id"] == created_agent["workspace_id"]
        assert body["config_version"] >= 1
        assert "current_config" in body
        assert "created_by" in body
        assert "created_at" in body
        assert "updated_at" in body
        assert "capabilities" in body
        assert "tools" in body

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}
        Scenario: anonymous caller
        Expected: 401 Unauthorized
        """
        r = httpx.get(f"{API}/api/v1/agents/{existing_agent_id}", timeout=TIMEOUT)
        assert r.status_code == 401

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: GET /api/v1/agents/nonexistent-id
        Scenario: agent_id does not exist
        Expected: 404 Not Found
        Source: metatron.agents.service -> AgentNotFoundError
        """
        r = httpx.get(
            f"{API}/api/v1/agents/nonexistent-agent-id",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404
