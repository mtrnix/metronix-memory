"""Tests for listing agents — GET /api/v1/agents/."""

from __future__ import annotations

import httpx

from .conftest import API, TIMEOUT, AGENT_NAME_PREFIX


class TestListAgents:
    """GET /api/v1/agents/ — list agents in workspace."""

    # type: positive, checks: [functional, auth]
    def test_returns_paginated_list(self, auth_headers, created_agent):
        """Endpoint: GET /api/v1/agents/
        Scenario: authenticated viewer lists agents
        Expected: 200, response has agents list, count, limit, offset, has_more.
                  Created agent appears in the list.
        Source: src/metatron/api/routes/agents.py:list_agents()
        """
        r = httpx.get(f"{API}/api/v1/agents/", headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert "agents" in body
        assert isinstance(body["agents"], list)
        assert body["count"] >= 1
        assert isinstance(body["limit"], int)
        assert isinstance(body["offset"], int)
        assert isinstance(body["has_more"], bool)
        ids = [a["id"] for a in body["agents"]]
        assert created_agent["id"] in ids

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self):
        """Endpoint: GET /api/v1/agents/
        Scenario: anonymous caller — no Authorization header
        Expected: 401 Unauthorized
        Source: metatron.api.dependencies -> require_viewer
        """
        r = httpx.get(f"{API}/api/v1/agents/", timeout=TIMEOUT)
        assert r.status_code == 401

    # type: positive, checks: [functional, pagination]
    def test_respects_limit_and_offset(self, auth_headers):
        """Endpoint: GET /api/v1/agents/?limit=1&offset=0
        Scenario: request with pagination params
        Expected: 200, at most 1 item in agents, count <= limit
        """
        r = httpx.get(
            f"{API}/api/v1/agents/?limit=1&offset=0",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["agents"]) <= 1
        assert body["limit"] == 1
        assert body["offset"] == 0

    # type: edge, checks: [validation]
    def test_returns_422_on_invalid_limit(self, auth_headers):
        """Endpoint: GET /api/v1/agents/?limit=-1
        Scenario: limit below minimum (ge=1)
        Expected: 422 Unprocessable Entity
        """
        r = httpx.get(
            f"{API}/api/v1/agents/?limit=-1",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 422

    # type: edge, checks: [validation]
    def test_returns_422_on_excessive_offset(self, auth_headers):
        """Endpoint: GET /api/v1/agents/?offset=99999
        Scenario: offset above maximum (le=10000)
        Expected: 422 Unprocessable Entity
        """
        r = httpx.get(
            f"{API}/api/v1/agents/?offset=99999",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 422

    # type: positive, checks: [functional, filtering]
    def test_filters_by_name_prefix(self, auth_headers, created_agent):
        """Endpoint: GET /api/v1/agents/?name_prefix=qa-test-
        Scenario: filter by name_prefix matching created agent
        Expected: 200, only agents with matching prefix returned
        """
        r = httpx.get(
            f"{API}/api/v1/agents/?name_prefix={AGENT_NAME_PREFIX}",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        for agent in body["agents"]:
            assert agent["name"].startswith(AGENT_NAME_PREFIX)

    # type: positive, checks: [functional, filtering]
    def test_filters_by_status(self, auth_headers, created_agent):
        """Endpoint: GET /api/v1/agents/?status=stopped
        Scenario: filter by status=stopped (all new agents are STOPPED)
        Expected: 200, only stopped agents
        """
        r = httpx.get(
            f"{API}/api/v1/agents/?status=stopped",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        for agent in body["agents"]:
            assert agent["status"] == "stopped"
        assert created_agent["id"] in [a["id"] for a in body["agents"]]

    # type: edge, checks: [validation]
    def test_rejects_mutually_exclusive_params(self, auth_headers):
        """Endpoint: GET /api/v1/agents/?status=stopped&include_archived=true
        Scenario: status filter and include_archived are mutually exclusive
        Expected: 400 Bad Request with descriptive detail
        Source: src/metatron/api/routes/agents.py:list_agents()
        """
        r = httpx.get(
            f"{API}/api/v1/agents/?status=stopped&include_archived=true",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 400
        assert "mutually exclusive" in r.text.lower()

    # type: edge, checks: [validation]
    def test_name_prefix_min_length(self, auth_headers):
        """Endpoint: GET /api/v1/agents/?name_prefix=
        Scenario: empty name_prefix (min_length=1)
        Expected: 422
        """
        r = httpx.get(
            f"{API}/api/v1/agents/?name_prefix=",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 422
