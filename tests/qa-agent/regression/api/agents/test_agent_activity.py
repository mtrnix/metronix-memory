"""Tests for agent activity — GET /api/v1/agents/{agent_id}/activity."""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT


class TestAgentActivity:
    """GET /api/v1/agents/{agent_id}/activity — paginated activity timeline."""

    # type: positive, checks: [functional]
    def test_returns_activity_events(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity
        Scenario: viewer fetches activity log for an existing agent
        Expected: 200, events list with count, limit, offset, has_more.
                  Each event has id, workspace_id, agent_id, event_type,
                  event_data, created_at.
        Source: src/metatron/api/routes/agents.py:get_agent_activity()
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert "events" in body
        assert isinstance(body["events"], list)
        assert isinstance(body["count"], int)
        assert isinstance(body["limit"], int)
        assert isinstance(body["offset"], int)
        assert isinstance(body["has_more"], bool)
        if body["events"]:
            ev = body["events"][0]
            assert "id" in ev
            assert ev["agent_id"] == existing_agent_id
            assert "event_type" in ev
            assert "created_at" in ev

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: GET /api/v1/agents/nonexistent-id/activity
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.get(
            f"{API}/api/v1/agents/nonexistent-agent-id/activity",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity",
            timeout=TIMEOUT,
        )
        assert r.status_code == 401

    # type: positive, checks: [functional, filtering]
    def test_returns_activity_with_since_param(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity?since=2026-01-01T00:00:00Z
        Scenario: filter activity by since timestamp
        Expected: 200, events within range
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity?since=2026-01-01T00%3A00%3A00Z",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200

    # type: positive, checks: [functional, pagination]
    def test_respects_limit(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity?limit=1
        Scenario: limit pagination
        Expected: 200, at most 1 event
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity?limit=1",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        assert len(r.json()["events"]) <= 1


class TestAgentActivitySummary:
    """GET /api/v1/agents/{agent_id}/activity/summary — aggregated stats."""

    # type: positive, checks: [functional]
    def test_returns_activity_summary(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity/summary
        Scenario: viewer fetches aggregated activity summary for an agent
        Expected: 200, contains period, since, until, total_events,
                  counts_by_event_type, counts_by_day
        Source: src/metatron/api/routes/agents.py:get_agent_activity_summary()
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity/summary",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["period"] == "7d"
        assert "since" in body
        assert "until" in body
        assert "total_events" in body
        assert isinstance(body["total_events"], int)
        assert "counts_by_event_type" in body
        assert "counts_by_day" in body

    # type: positive, checks: [functional]
    def test_summary_with_custom_period(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity/summary?period=30d
        Scenario: request with 30d period
        Expected: 200, period reflects requested value
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity/summary?period=30d",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        assert r.json()["period"] == "30d"

    # type: edge, checks: [validation]
    def test_returns_400_on_invalid_period(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity/summary?period=invalid
        Scenario: period value not in known set (1d|7d|30d|90d)
        Expected: 400 Bad Request
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity/summary?period=invalid",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 400

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: GET /api/v1/agents/nonexistent-id/activity/summary
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.get(
            f"{API}/api/v1/agents/nonexistent-agent-id/activity/summary",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/activity/summary
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/activity/summary",
            timeout=TIMEOUT,
        )
        assert r.status_code == 401
