"""Shared fixtures for the agents zone API tests.

All tests in this directory use JWT auth obtained from the QA admin account.
Created agents have the ``qa-test-`` prefix and are cleaned up after each
mutation test via fixture teardown.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator

import httpx
import pytest

API = os.environ.get("BACKEND_URL", "http://drp-m.mtrnix.com:8000")
TIMEOUT = 30
AGENT_NAME_PREFIX = "qa-test-"


@pytest.fixture(scope="module")
def auth_token() -> str:
    """Module-scoped JWT: login as QA admin."""
    email = os.environ["QA_UI_EMAIL"]
    password = os.environ["QA_UI_PASSWORD"]
    r = httpx.post(
        f"{API}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["token"]


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def unique_name() -> str:
    """Generate a unique agent name with the qa-test- prefix."""
    return f"{AGENT_NAME_PREFIX}{uuid.uuid4().hex[:8]}"


@pytest.fixture
def created_agent(auth_headers: dict[str, str], unique_name: str) -> Generator[dict, None, None]:
    """Create an agent, yield its full response dict, then soft-delete it."""
    # Create
    payload = {
        "name": unique_name,
        "model": "deepseek/deepseek-v4-flash",
        "capabilities": ["qa"],
        "tools": [],
    }
    r = httpx.post(
        f"{API}/api/v1/agents/",
        headers=auth_headers,
        json=payload,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    agent = r.json()
    agent_id = agent["id"]

    yield agent

    # Teardown — soft-delete
    try:  # noqa: SIM105
        httpx.delete(
            f"{API}/api/v1/agents/{agent_id}",
            headers=auth_headers,
            timeout=TIMEOUT,
        )
    except Exception:
        pass  # Best-effort cleanup


@pytest.fixture
def existing_agent_id(created_agent: dict) -> str:
    """Shortcut: just the agent ID from created_agent."""
    return created_agent["id"]
