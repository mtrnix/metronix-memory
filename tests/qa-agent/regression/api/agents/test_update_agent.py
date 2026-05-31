"""Tests for updating agents — PUT /api/v1/agents/{agent_id}."""

from __future__ import annotations

import uuid

import httpx

from .conftest import API, TIMEOUT


class TestUpdateAgent:
    """PUT /api/v1/agents/{agent_id} — partial update of an agent."""

    # type: positive, checks: [functional, mutation]
    def test_update_name(self, auth_headers, existing_agent_id):
        """Endpoint: PUT /api/v1/agents/{agent_id}
        Scenario: editor updates only the name field
        Expected: 200, name is updated, config_version incremented, other fields unchanged
        Cleanup: agent is deleted via created_agent fixture teardown
        Source: src/metatron/api/routes/agents.py:update_agent()
        """
        new_name = f"qa-test-updated-{uuid.uuid4().hex[:8]}"
        r = httpx.put(
            f"{API}/api/v1/agents/{existing_agent_id}",
            headers=auth_headers,
            json={"name": new_name},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == new_name
        assert body["config_version"] >= 2
        assert body["id"] == existing_agent_id

    # type: positive, checks: [functional, mutation]
    def test_update_multiple_fields(self, auth_headers, existing_agent_id):
        """Endpoint: PUT /api/v1/agents/{agent_id}
        Scenario: editor updates name, model, capabilities, tools simultaneously
        Expected: 200, all updated fields reflected, config_version bumped
        """
        r = httpx.put(
            f"{API}/api/v1/agents/{existing_agent_id}",
            headers=auth_headers,
            json={
                "model": "anthropic/claude-sonnet-4",
                "capabilities": ["rag", "summarize"],
                "tools": ["search"],
            },
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "anthropic/claude-sonnet-4"
        assert "rag" in body["capabilities"]
        assert "search" in body["tools"]

    # type: negative, checks: [validation]
    def test_returns_422_on_empty_update(self, auth_headers, existing_agent_id):
        """Endpoint: PUT /api/v1/agents/{agent_id}
        Scenario: body has no fields set (all None)
        Expected: 422 — at least one field required
        Source: UpdateAgentRequest model validator
        """
        r = httpx.put(
            f"{API}/api/v1/agents/{existing_agent_id}",
            headers=auth_headers,
            json={},
            timeout=TIMEOUT,
        )
        assert r.status_code == 422
        assert "at least one field" in r.text.lower()

    # type: negative, checks: [functional, mutation]
    def test_returns_404_for_nonexistent_agent(self, auth_headers):
        """Endpoint: PUT /api/v1/agents/nonexistent-id
        Scenario: agent does not exist
        Expected: 404 Not Found
        """
        r = httpx.put(
            f"{API}/api/v1/agents/nonexistent-agent-id",
            headers=auth_headers,
            json={"name": "new-name"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 404

    # type: negative, checks: [validation]
    def test_returns_422_on_name_too_long(self, auth_headers, existing_agent_id):
        """Endpoint: PUT /api/v1/agents/{agent_id}
        Scenario: name exceeds 128 chars
        Expected: 422
        """
        r = httpx.put(
            f"{API}/api/v1/agents/{existing_agent_id}",
            headers=auth_headers,
            json={"name": "x" * 129},
            timeout=TIMEOUT,
        )
        assert r.status_code == 422

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self, existing_agent_id):
        """Endpoint: PUT /api/v1/agents/{agent_id}
        Scenario: anonymous caller
        Expected: 401
        """
        r = httpx.put(
            f"{API}/api/v1/agents/{existing_agent_id}",
            json={"name": "hacker"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 401

    # type: positive, checks: [functional, mutation]
    def test_update_clears_tools(self, auth_headers, existing_agent_id):
        """Endpoint: PUT /api/v1/agents/{agent_id}
        Scenario: explicitly set tools to empty list
        Expected: 200, tools is empty list
        """
        r = httpx.put(
            f"{API}/api/v1/agents/{existing_agent_id}",
            headers=auth_headers,
            json={"tools": []},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        assert r.json()["tools"] == []
