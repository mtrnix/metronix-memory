"""Tests for creating agents — POST /api/v1/agents/."""

from __future__ import annotations

import uuid

import httpx
import pytest

from .conftest import API, TIMEOUT


class TestCreateAgent:
    """POST /api/v1/agents/ — create a new agent."""

    # type: positive, checks: [functional, mutation]
    def test_create_minimal(self, auth_headers):
        """Endpoint: POST /api/v1/agents/
        Scenario: editor creates agent with only required fields (name, model)
        Expected: 201, response contains id, status=stopped, config_version=1,
                  defaults for optional fields (empty lists/dicts)
        Cleanup: created agent is soft-deleted in teardown
        Source: src/metatron/api/routes/agents.py:create_agent()
        """
        name = f"qa-test-{uuid.uuid4().hex[:8]}"
        payload = {"name": name, "model": "deepseek/deepseek-v4-flash"}
        r = httpx.post(f"{API}/api/v1/agents/", headers=auth_headers, json=payload, timeout=TIMEOUT)
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == name
        assert body["status"] == "stopped"
        assert body["config_version"] == 1
        assert body["capabilities"] == []
        assert body["tools"] == []
        assert body["memory_bindings"] == {}
        assert body["budget"] == {}

        # Cleanup
        httpx.delete(f"{API}/api/v1/agents/{body['id']}", headers=auth_headers, timeout=TIMEOUT)

    # type: positive, checks: [functional, mutation]
    def test_create_with_all_optional_fields(self, auth_headers):
        """Endpoint: POST /api/v1/agents/
        Scenario: editor creates agent with all optional fields filled
        Expected: 201, all provided fields reflected in response
        Cleanup: deleted via teardown
        """
        name = f"qa-test-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": name,
            "model": "gpt-4o",
            "capabilities": ["qa", "search"],
            "tools": ["web_search", "calculator"],
            "memory_bindings": {"max_records": 100},
            "budget": {"max_daily_cost": 5.0},
        }
        r = httpx.post(f"{API}/api/v1/agents/", headers=auth_headers, json=payload, timeout=TIMEOUT)
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == name
        assert body["model"] == "gpt-4o"
        assert body["capabilities"] == ["qa", "search"]
        assert body["tools"] == ["web_search", "calculator"]
        assert body["memory_bindings"] == {"max_records": 100}
        assert body["budget"] == {"max_daily_cost": 5.0}

        httpx.delete(f"{API}/api/v1/agents/{body['id']}", headers=auth_headers, timeout=TIMEOUT)

    # type: negative, checks: [validation]
    def test_returns_409_on_duplicate_name(self, auth_headers, created_agent, unique_name):
        """Endpoint: POST /api/v1/agents/
        Scenario: create agent with same name as an existing non-archived agent
        Expected: 409 Conflict
        Source: metatron.agents.service -> AgentNameConflictError
        """
        payload = {"name": created_agent["name"], "model": "deepseek/deepseek-v4-flash"}
        r = httpx.post(f"{API}/api/v1/agents/", headers=auth_headers, json=payload, timeout=TIMEOUT)
        assert r.status_code == 409

    # type: negative, checks: [validation]
    def test_returns_422_without_name(self, auth_headers):
        """Endpoint: POST /api/v1/agents/
        Scenario: body missing required field 'name'
        Expected: 422 Validation Error
        """
        r = httpx.post(
            f"{API}/api/v1/agents/",
            headers=auth_headers,
            json={"model": "deepseek/deepseek-v4-flash"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 422

    # type: negative, checks: [validation]
    def test_returns_422_on_empty_name(self, auth_headers):
        """Endpoint: POST /api/v1/agents/
        Scenario: name field is empty string (min_length=1)
        Expected: 422 Validation Error
        """
        r = httpx.post(
            f"{API}/api/v1/agents/",
            headers=auth_headers,
            json={"name": "", "model": "deepseek/deepseek-v4-flash"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 422

    # type: negative, checks: [validation]
    def test_returns_422_on_name_too_long(self, auth_headers):
        """Endpoint: POST /api/v1/agents/
        Scenario: name exceeds 128 characters
        Expected: 422 Validation Error
        """
        r = httpx.post(
            f"{API}/api/v1/agents/",
            headers=auth_headers,
            json={"name": "x" * 129, "model": "deepseek/deepseek-v4-flash"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 422

    # type: negative, checks: [validation]
    def test_returns_422_on_capability_too_long(self, auth_headers):
        """Endpoint: POST /api/v1/agents/
        Scenario: capability entry exceeds 128 chars
        Expected: 422 Validation Error
        """
        r = httpx.post(
            f"{API}/api/v1/agents/",
            headers=auth_headers,
            json={
                "name": f"qa-test-{uuid.uuid4().hex[:8]}",
                "model": "deepseek/deepseek-v4-flash",
                "capabilities": ["x" * 129],
            },
            timeout=TIMEOUT,
        )
        assert r.status_code == 422

    # type: negative, checks: [auth]
    def test_returns_401_without_token(self):
        """Endpoint: POST /api/v1/agents/
        Scenario: anonymous caller
        Expected: 401 Unauthorized
        """
        r = httpx.post(
            f"{API}/api/v1/agents/",
            json={"name": "test", "model": "deepseek/deepseek-v4-flash"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 401

    # type: edge, checks: [validation]
    def test_returns_422_on_memory_bindings_oversize(self, auth_headers, unique_name):
        """Endpoint: POST /api/v1/agents/
        Scenario: memory_bindings serialized size exceeds 32 KiB
        Expected: 422 Validation Error
        Source: src/metatron/api/routes/agents.py:_validate_opaque_mapping()
        """
        huge_binding = {"data": "x" * 40_000}
        r = httpx.post(
            f"{API}/api/v1/agents/",
            headers=auth_headers,
            json={"name": unique_name, "model": "deepseek/deepseek-v4-flash", "memory_bindings": huge_binding},
            timeout=TIMEOUT,
        )
        assert r.status_code == 422
