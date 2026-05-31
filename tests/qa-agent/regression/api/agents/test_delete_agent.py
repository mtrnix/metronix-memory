"""Tests for deleting (soft-deleting) agents — DELETE /api/v1/agents/{agent_id}."""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT


class TestDeleteAgent:
    """DELETE /api/v1/agents/{agent_id} — soft-delete (archive) an agent."""

    # type: positive, checks: [functional, mutation]
    def test_soft_deletes_agent(self, auth_headers, created_agent):
        """Endpoint: DELETE /api/v1/agents/{agent_id}
        Scenario: editor soft-deletes an existing active agent
        Expected: 204 No Content. Subsequent GET returns 404 (or agent is
                  archived and hidden from default list).
        Cleanup: agent was created via fixture
        Source: src/metatron/api/routes/agents.py:delete_agent()
        """
        agent_id = created_agent["id"]
        r = httpx.delete(
            f"{API}/api/v1/agents/{agent_id}",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 204

        # Verify — agent should not appear in default list
        r2 = httpx.get(f"{API}/api/v1/agents/", headers=auth_headers, timeout=TIMEOUT)
        assert r2.status_code == 200
        ids = [a["id"] for a in r2.json()["agents"]]
        assert agent_id not in ids, f"Deleted agent {agent_id} still appears in default list"

        # But should appear with include_archived=true
        r3 = httpx.get(
            f"{API}/api/v1/agents/?include_archived=true",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r3.status_code == 200
        archived_ids = [a["id"] for a in r3.json()["agents"]]
        assert agent_id in archived_ids, f"Deleted agent {agent_id} not found with include_archived=true"

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: DELETE /api/v1/agents/nonexistent-id
        Scenario: agent does not exist
        Expected: 404 Not Found
        """
        r = httpx.delete(
            f"{API}/api/v1/agents/nonexistent-agent-id",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: DELETE /api/v1/agents/{agent_id}
        Scenario: anonymous caller
        Expected: 401 Unauthorized
        """
        r = httpx.delete(f"{API}/api/v1/agents/{existing_agent_id}", timeout=TIMEOUT)
        assert r.status_code == 401
