"""Tests for agent memory health — GET /api/v1/agents/{agent_id}/memory/health."""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT


class TestAgentMemoryHealth:
    """GET /api/v1/agents/{agent_id}/memory/health — read-only health stats."""

    # type: positive, checks: [functional]
    def test_returns_health_stats(self, auth_headers, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/memory/health
        Scenario: viewer fetches memory health for an existing agent
        Expected: 200, response contains agent_id, total_records, total_archived,
                  growth_rate_per_day, growth_timeseries, unused_records,
                  unused_threshold_days, duplicate_ratio, duplicate_clusters_count,
                  source_distribution, computed_at
        Source: src/metronix/api/routes/agents.py:get_agent_memory_health()
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/memory/health",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["agent_id"] == existing_agent_id
        assert "total_records" in body
        assert isinstance(body["total_records"], int)
        assert "total_archived" in body
        assert isinstance(body["growth_rate_per_day"], float)
        assert "growth_timeseries" in body
        assert isinstance(body["growth_timeseries"], list)
        assert "unused_records" in body
        assert "unused_threshold_days" in body
        assert "duplicate_ratio" in body
        assert isinstance(body["duplicate_ratio"], (int, float))
        assert "duplicate_clusters_count" in body
        assert "source_distribution" in body
        assert isinstance(body["source_distribution"], dict)
        assert "computed_at" in body

    # type: negative, checks: [functional]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: GET /api/v1/agents/nonexistent-id/memory/health
        Scenario: agent does not exist
        Expected: 404
        """
        r = httpx.get(
            f"{API}/api/v1/agents/nonexistent-agent-id/memory/health",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: GET /api/v1/agents/{agent_id}/memory/health
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.get(
            f"{API}/api/v1/agents/{existing_agent_id}/memory/health",
            timeout=TIMEOUT,
        )
        assert r.status_code == 401
