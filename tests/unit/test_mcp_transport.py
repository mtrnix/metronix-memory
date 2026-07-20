"""Regression coverage for hosted MCP transport session isolation."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response
from starlette.applications import Starlette
from starlette.routing import Mount

from metronix.api.app import create_app, mcp_server
from metronix.auth.jwt import create_token
from metronix.core.config import Settings
from metronix.mcp.config import resolve_workspace_id
from metronix.mcp.principal import get_current_principal

_SECRET = "stateless-mcp-test-secret-at-least-32-bytes"
_PROTOCOL_VERSION = "2025-03-26"
_TEST_TOOL_NAME = "test_authenticated_principal"
_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "metronix-test", "version": "1"},
    },
}
_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _post_rpc(
    client: TestClient,
    token: str,
    request: dict[str, Any],
) -> Response:
    return client.post(
        "/mcp",
        json=request,
        headers={
            **_MCP_HEADERS,
            "Authorization": f"Bearer {token}",
            "MCP-Protocol-Version": _PROTOCOL_VERSION,
        },
    )


def _sse_payload(response: Response) -> dict[str, Any]:
    data = next(
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    )
    payload: dict[str, Any] = json.loads(data)
    return payload


def test_mounted_stateless_mcp_authorizes_each_tool_call_with_its_request_principal() -> None:
    @mcp_server.tool(name=_TEST_TOOL_NAME)
    async def authenticated_principal(workspace_id: str) -> dict[str, str]:
        """Expose the principal observed by an authorization-sensitive test tool."""
        principal = get_current_principal()
        if principal is None:
            raise PermissionError("JWT principal required")
        return {
            "user_id": principal.user_id,
            "workspace_id": resolve_workspace_id(workspace_id),
        }

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
    principals = {
        user_id: create_token(
            user_id=user_id,
            role="viewer",
            workspace_ids=[workspace_id],
            secret_key=_SECRET,
        )
        for user_id, workspace_id in (("user-a", "ws-a"), ("user-b", "ws-b"))
    }

    try:
        with TestClient(transport_app) as client:
            initialize_responses = [
                _post_rpc(client, principals[user_id], _INITIALIZE_REQUEST)
                for user_id in ("user-a", "user-b")
            ]
            initialized_responses = [
                _post_rpc(
                    client,
                    principals[user_id],
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                )
                for user_id in ("user-a", "user-b")
            ]

            def call_tool(user_id: str, workspace_id: str, request_id: int) -> Response:
                return _post_rpc(
                    client,
                    principals[user_id],
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {
                            "name": _TEST_TOOL_NAME,
                            "arguments": {"workspace_id": workspace_id},
                        },
                    },
                )

            user_a_call = call_tool("user-a", "ws-a", 2)
            user_b_reusing_a_context = call_tool("user-b", "ws-a", 3)
            user_b_call = call_tool("user-b", "ws-b", 4)
    finally:
        mcp_server._tool_manager.remove_tool(_TEST_TOOL_NAME)

    assert [response.status_code for response in initialize_responses] == [200, 200]
    assert [response.status_code for response in initialized_responses] == [202, 202]
    assert _sse_payload(initialize_responses[0])["result"]["protocolVersion"] == _PROTOCOL_VERSION

    all_responses = [
        *initialize_responses,
        *initialized_responses,
        user_a_call,
        user_b_reusing_a_context,
        user_b_call,
    ]
    assert all(response.headers.get("mcp-session-id") is None for response in all_responses)

    assert _sse_payload(user_a_call)["result"] == {
        "content": [
            {
                "type": "text",
                "text": '{\n  "user_id": "user-a",\n  "workspace_id": "ws-a"\n}',
            }
        ],
        "structuredContent": {"user_id": "user-a", "workspace_id": "ws-a"},
        "isError": False,
    }
    assert _sse_payload(user_b_reusing_a_context)["result"]["isError"] is True
    assert (
        "No access to workspace 'ws-a'"
        in (_sse_payload(user_b_reusing_a_context)["result"]["content"][0]["text"])
    )
    assert _sse_payload(user_b_call)["result"] == {
        "content": [
            {
                "type": "text",
                "text": '{\n  "user_id": "user-b",\n  "workspace_id": "ws-b"\n}',
            }
        ],
        "structuredContent": {"user_id": "user-b", "workspace_id": "ws-b"},
        "isError": False,
    }
