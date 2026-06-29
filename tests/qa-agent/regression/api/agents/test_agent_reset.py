"""Tests for resetting agent memory — POST /api/v1/agents/{agent_id}/reset.

Resets an agent's memory after taking an automatic pre_reset snapshot.
"""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT


class TestResetAgentMemory:
    """POST /api/v1/agents/{agent_id}/reset — wipe + pre-snapshot."""

    # type: positive, checks: [functional, mutation]
    def test_reset_agent_memory(self, auth_headers, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/reset
        Scenario: editor resets agent memory (takes pre_reset snapshot first)
        Expected: 200, response contains snapshot_id (string) and deleted_count (int >= 0)
        Cleanup: agent is deleted via fixture teardown
        Source: src/metronix/api/routes/agents.py:reset_agent_memory()
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/reset",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"Reset failed: {r.text}"
        body = r.json()
        assert "snapshot_id" in body
        assert isinstance(body["snapshot_id"], str)
        assert "deleted_count" in body
        assert isinstance(body["deleted_count"], int)
        assert body["deleted_count"] >= 0

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: POST /api/v1/agents/nonexistent-id/reset
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.post(
            f"{API}/api/v1/agents/nonexistent-agent-id/reset",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/reset
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/reset",
            timeout=TIMEOUT,
        )
        assert r.status_code == 401
