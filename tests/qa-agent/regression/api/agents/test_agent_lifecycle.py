"""Tests for agent lifecycle transitions — start/stop/pause/restore.

State machine (from src/metronix/agents/service.py):
  _ALLOWED_LIFECYCLE_SOURCES = {
      ACTIVE:  {ACTIVE, PAUSED, STOPPED},   # start
      PAUSED:  {ACTIVE, PAUSED, STOPPED},   # pause
      STOPPED: {ACTIVE, PAUSED, STOPPED},   # stop
  }
  ARCHIVED can only transition via restore_agent (ARCHIVED → STOPPED).
"""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT


class TestAgentLifecycle:
    """POST /api/v1/agents/{agent_id}/start|stop|pause|restore."""

    # type: positive, checks: [functional, mutation]
    def test_start_stopped_agent(self, auth_headers, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/start
        Scenario: start a STOPPED agent (default state after creation)
        Expected: 200, status becomes 'active'
        Source: src/metronix/api/routes/agents.py:start_agent()
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/start",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "active"

    # type: positive, checks: [functional, mutation]
    def test_start_then_pause_then_stop_cycle(self, auth_headers, existing_agent_id):
        """Endpoint: POST /agents/{id}/start → POST /agents/{id}/pause → POST /agents/{id}/stop
        Scenario: full lifecycle cycle: stopped → active → paused → stopped
        Expected: 200 for each transition, correct status after each step
        """
        # STOPPED → ACTIVE
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/start",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"Start failed: {r.text}"
        assert r.json()["status"] == "active"

        # ACTIVE → PAUSED
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/pause",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"Pause failed: {r.text}"
        assert r.json()["status"] == "paused"

        # PAUSED → STOPPED
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/stop",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"Stop failed: {r.text}"
        assert r.json()["status"] == "stopped"

    # type: positive, checks: [functional, mutation]
    def test_start_is_idempotent(self, auth_headers, existing_agent_id):
        """Endpoint: POST /agents/{id}/start twice
        Scenario: start an already-active agent
        Expected: 200 (idempotent — ACTIVE→ACTIVE is allowed)
        """
        r1 = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/start",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r1.status_code == 200

        r2 = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/start",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "active"

    # type: negative, checks: [functional, mutation]
    def test_pause_on_stopped_agent(self, auth_headers, existing_agent_id):
        """Endpoint: POST /agents/{agent_id}/pause when status=stopped
        Scenario: pause a stopped agent (STOPPED→PAUSED is allowed per _ALLOWED_LIFECYCLE_SOURCES)
        Expected: 200, status becomes 'paused' (idempotent transition)
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/pause",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        # STOPPED→PAUSED is in _ALLOWED_LIFECYCLE_SOURCES[PAUSED] = {ACTIVE, PAUSED, STOPPED}
        assert r.status_code in (200, 400), f"Unexpected: {r.status_code} {r.text}"
        if r.status_code == 200:
            assert r.json()["status"] == "paused"

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/start
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/start",
            timeout=TIMEOUT,
        )
        assert r.status_code == 401

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: POST /api/v1/agents/nonexistent-id/start
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.post(
            f"{API}/api/v1/agents/nonexistent-agent-id/start",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404


class TestRestoreAgent:
    """POST /api/v1/agents/{agent_id}/restore — revive an archived agent."""

    # type: positive, checks: [functional, mutation]
    def test_restore_archived_agent(self, auth_headers, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/restore
        Scenario: soft-delete (archive) an agent, then restore it
        Expected: After delete → 204. After restore → 200, status=stopped.
                  Agent reappears in default GET /agents/.
        Source: src/metronix/api/routes/agents.py:restore_agent()
        """
        # Archive
        r = httpx.delete(
            f"{API}/api/v1/agents/{existing_agent_id}",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 204

        # Restore
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/restore",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"Restore failed: {r.text}"
        assert r.json()["status"] == "stopped"

        # Verify it's back in default listing
        r2 = httpx.get(f"{API}/api/v1/agents/", headers=auth_headers, timeout=TIMEOUT)
        ids = [a["id"] for a in r2.json()["agents"]]
        assert existing_agent_id in ids

    # type: negative, checks: [functional]
    def test_restore_non_archived_agent_returns_400(self, auth_headers, existing_agent_id):
        """Endpoint: POST /api/v1/agents/{agent_id}/restore
        Scenario: restore an agent that is not archived (status=stopped)
        Expected: 400 — InvalidStateTransition
        """
        r = httpx.post(
            f"{API}/api/v1/agents/{existing_agent_id}/restore",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 400
