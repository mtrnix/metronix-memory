"""Regression coverage for hosted MCP transport session isolation."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

from metronix.api.app import create_app, mcp_server
from metronix.auth.jwt import create_token
from metronix.core.config import Settings

_SECRET = "stateless-mcp-test-secret-at-least-32-bytes"
_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "metronix-test", "version": "1"},
    },
}
_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_mounted_mcp_does_not_issue_sessions_reusable_across_principals() -> None:
    app = create_app(
        Settings(
            AUTH_ENABLED=True,
            METRONIX_ENV="development",
            METRONIX_SECRET_KEY=_SECRET,
        )
    )

    @asynccontextmanager
    async def mcp_lifespan(_app: Starlette):
        async with mcp_server.session_manager.run():
            yield

    # Run the real FastAPI middleware and mounted /mcp route while limiting
    # lifespan startup to the MCP manager (the full app also starts databases).
    transport_app = Starlette(routes=[Mount("/", app=app)], lifespan=mcp_lifespan)
    principals = [
        create_token(
            user_id=user_id,
            role="viewer",
            workspace_ids=["ws-a"],
            secret_key=_SECRET,
        )
        for user_id in ("user-a", "user-b")
    ]

    with TestClient(transport_app) as client:
        responses = [
            client.post(
                "/mcp",
                json=_INITIALIZE_REQUEST,
                headers={**_MCP_HEADERS, "Authorization": f"Bearer {token}"},
            )
            for token in principals
        ]

    assert [response.status_code for response in responses] == [200, 200]
    assert [response.headers.get("mcp-session-id") for response in responses] == [None, None]
