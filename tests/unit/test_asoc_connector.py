"""Unit tests for AsocConnector (MCP-based, MTRNIX-370 Phase 3).

Mocks ``AsocMcpClient.invoke`` — no live ASOC instance or httpx required.
All tests run fully in-process and in-memory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.connectors.asoc import AsocConnector
from metatron.core.exceptions import ConnectorError
from metatron.core.models import Connection
from metatron.integrations.asoc_mcp_client import (
    AsocToolCallResult,
    McpAuthError,
    McpUnavailableError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connection(connection_id: str = "conn-1") -> Connection:
    return Connection(
        id=connection_id,
        workspace_id="ws-test",
        connector_type="asoc",
        name="test-asoc",
    )


def _valid_config() -> dict[str, str]:
    return {
        "project_id": "proj-uuid-1",
        "asoc_instance_id": "inst-1",
    }


def _make_mcp_client(invoke_side_effect: Any = None) -> MagicMock:
    """Return a MagicMock with invoke as an AsyncMock."""
    client = MagicMock()
    if invoke_side_effect is not None:
        client.invoke = AsyncMock(side_effect=invoke_side_effect)
    else:
        client.invoke = AsyncMock(return_value=_empty_list_result())
    return client


def _list_result(items: list[dict], next_cursor: str | None = None) -> AsocToolCallResult:
    """Build an AsocToolCallResult with an items list payload."""
    import json

    payload: dict[str, Any] = {"items": items}
    if next_cursor:
        payload["next_cursor"] = next_cursor
    return AsocToolCallResult(
        tool="asoc_list_issues",
        content=[{"type": "text", "text": json.dumps(payload)}],
        is_error=False,
    )


def _empty_list_result() -> AsocToolCallResult:
    return _list_result([])


def _raw_issue(issue_id: str = "issue-1") -> dict[str, Any]:
    return {
        "id": issue_id,
        "title": "XSS vuln",
        "description": "details",
        "severity": 3,
        "status": "open",
        "layer_id": "layer-1",
        "view_id": f"ISS-{issue_id}",
        "created_by": "alice",
        "created_at": "2025-02-01T00:00:00Z",
        "updated_at": "2025-06-05T00:00:00Z",
        "url_hint": f"/projects/proj-uuid-1/issues/ISS-{issue_id}",
    }


def _raw_project(project_id: str = "proj-uuid-1") -> dict[str, Any]:
    return {
        "id": project_id,
        "name": "Test Project",
        "description": "desc",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-06-01T00:00:00Z",
        "url_hint": f"/projects/{project_id}",
    }


async def _make_configured_connector(mcp_client: Any = None) -> AsocConnector:
    """Create and configure an AsocConnector with an optional MCP client."""
    c = AsocConnector()
    await c.configure(_make_connection(), _valid_config())
    if mcp_client is not None:
        c.set_mcp_client(mcp_client)
    return c


# ---------------------------------------------------------------------------
# TestConfigure
# ---------------------------------------------------------------------------


class TestConfigure:
    async def test_happy_path(self) -> None:
        c = AsocConnector()
        await c.configure(_make_connection(), _valid_config())
        assert c._project_id == "proj-uuid-1"
        assert c._instance_id == "inst-1"

    @pytest.mark.parametrize(
        "missing_key",
        ["project_id", "asoc_instance_id"],
    )
    async def test_missing_key_raises(self, missing_key: str) -> None:
        config = _valid_config()
        del config[missing_key]
        c = AsocConnector()
        with pytest.raises(ConnectorError, match="asoc.configure.missing_key"):
            await c.configure(_make_connection(), config)

    @pytest.mark.parametrize(
        "empty_key",
        ["project_id", "asoc_instance_id"],
    )
    async def test_empty_value_raises(self, empty_key: str) -> None:
        config = {**_valid_config(), empty_key: ""}
        c = AsocConnector()
        with pytest.raises(ConnectorError, match="asoc.configure.missing_key"):
            await c.configure(_make_connection(), config)

    async def test_set_mcp_client(self) -> None:
        c = AsocConnector()
        await c.configure(_make_connection(), _valid_config())
        assert c._mcp is None
        client = _make_mcp_client()
        c.set_mcp_client(client)
        assert c._mcp is client


# ---------------------------------------------------------------------------
# TestFetchBootstrap
# ---------------------------------------------------------------------------


class TestFetchBootstrap:
    async def test_iterates_all_entity_types_produces_documents(self) -> None:
        """Verify entity types produce Documents when MCP returns items."""
        issue_result = _list_result([_raw_issue("issue-1")])
        project_result = _list_result([_raw_project()])

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            if tool_name == "asoc_list_projects":
                return project_result
            if tool_name == "asoc_list_issues":
                return issue_result
            # Per-issue tools: asoc_get_issue_comments, asoc_get_issue_history
            if tool_name in ("asoc_get_issue_comments", "asoc_get_issue_history"):
                return _empty_list_result()
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        docs = await c.fetch("ws-1")
        assert len(docs) >= 1

    async def test_no_mcp_client_raises(self) -> None:
        c = await _make_configured_connector()  # no mcp client
        with pytest.raises(ConnectorError, match="not configured"):
            await c.fetch("ws-1")

    async def test_empty_project_returns_empty_list(self) -> None:
        mcp = _make_mcp_client()  # always returns empty list
        c = await _make_configured_connector(mcp)
        docs = await c.fetch("ws-1")
        assert docs == []

    async def test_paginated_entity_type(self) -> None:
        """Two pages via cursor/next_cursor → all items collected."""
        page1_items = [
            {
                "id": f"layer-{i}",
                "name": f"Layer {i}",
                "kind": "svc",
                "url_hint": f"/l/{i}",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
            }
            for i in range(50)
        ]
        page2_items = [
            {
                "id": "layer-50",
                "name": "Last",
                "kind": "svc",
                "url_hint": "/l/50",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
            }
        ]

        call_count: dict[str, int] = {"n": 0}

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            if tool_name == "asoc_list_layers":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return _list_result(page1_items, next_cursor="page2-cursor")
                return _list_result(page2_items)
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        docs = await c.fetch("ws-1")
        layer_docs = [d for d in docs if d.metadata.get("entity_type") == "layer"]
        assert len(layer_docs) == 51

    async def test_malformed_entity_skipped(self) -> None:
        """Entity missing 'id' must be skipped (logged as warning, not raised)."""
        malformed_issue = {"title": "no id here", "url_hint": "/noid"}

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            if tool_name == "asoc_list_issues":
                return _list_result([malformed_issue])
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        docs = await c.fetch("ws-1")
        issue_docs = [d for d in docs if d.metadata.get("entity_type") == "issue"]
        assert issue_docs == []

    async def test_url_hint_set_on_document(self) -> None:
        """Document.url is set from url_hint in the MCP response."""
        issue = {**_raw_issue("i-1"), "url_hint": "/projects/proj/issues/ISS-1"}

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            if tool_name == "asoc_list_issues":
                return _list_result([issue])
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        docs = await c.fetch("ws-1")
        issue_docs = [d for d in docs if d.metadata.get("entity_type") == "issue"]
        assert len(issue_docs) == 1
        assert issue_docs[0].url == "/projects/proj/issues/ISS-1"

    async def test_missing_url_hint_leaves_empty_url(self) -> None:
        """When url_hint is absent, Document.url is empty (no crash)."""
        issue_no_hint = {k: v for k, v in _raw_issue("i-1").items() if k != "url_hint"}

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            if tool_name == "asoc_list_issues":
                return _list_result([issue_no_hint])
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        docs = await c.fetch("ws-1")
        issue_docs = [d for d in docs if d.metadata.get("entity_type") == "issue"]
        assert len(issue_docs) == 1
        assert issue_docs[0].url == ""


# ---------------------------------------------------------------------------
# TestFetchIncremental
# ---------------------------------------------------------------------------


class TestFetchIncremental:
    async def test_updated_after_param_passed_when_since_set(self) -> None:
        """When since is set, updated_after is included in MCP arguments."""
        since = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        captured_args: list[dict] = []

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            captured_args.append({"tool": tool_name, "args": dict(arguments)})
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        await c.fetch("ws-1", since=since)

        ua_calls = [x for x in captured_args if "updated_after" in x["args"]]
        assert len(ua_calls) > 0
        assert since.isoformat() in ua_calls[0]["args"]["updated_after"]


# ---------------------------------------------------------------------------
# TestFetchResumeHints
# ---------------------------------------------------------------------------


class TestFetchResumeHints:
    async def test_after_resource_skips_earlier_types(self) -> None:
        """after_resource='scan_result' skips project, layer, issue, etc."""
        invoked_tools: list[str] = []

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            invoked_tools.append(tool_name)
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        await c.fetch("ws-1", after_resource="scan_result")

        # project, layer, issue should NOT have been fetched
        assert "asoc_list_projects" not in invoked_tools
        assert "asoc_list_layers" not in invoked_tools
        assert "asoc_list_issues" not in invoked_tools
        # scan_result tool SHOULD have been called
        assert "asoc_list_scan_results" in invoked_tools

    async def test_after_id_skips_within_type(self) -> None:
        """after_id='issue-1' means items up to and including issue-1 are skipped."""
        items = [_raw_issue(f"issue-{i}") for i in range(1, 4)]

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            if tool_name == "asoc_list_issues":
                return _list_result(items)
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        docs = await c.fetch("ws-1", after_resource="issue", after_id="issue-1")

        issue_docs = [d for d in docs if d.metadata.get("entity_type") == "issue"]
        source_ids = [d.source_id for d in issue_docs]
        assert "issue-1" not in source_ids
        assert "issue-2" in source_ids
        assert "issue-3" in source_ids

    async def test_invalid_after_resource_falls_back_to_start(self) -> None:
        """Invalid after_resource is ignored and fetch starts from the beginning."""
        invoked_tools: list[str] = []

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            invoked_tools.append(tool_name)
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        await c.fetch("ws-1", after_resource="nonexistent_type", after_id="some-id")

        assert "asoc_list_projects" in invoked_tools

    async def test_resume_composes_with_since(self) -> None:
        """after_resource + since: resume skips types AND passes updated_after."""
        since = datetime(2025, 6, 1, tzinfo=UTC)
        captured_args: list[dict] = []

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            captured_args.append({"tool": tool_name, "args": dict(arguments)})
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        await c.fetch("ws-1", since=since, after_resource="scan_result")

        # project/layer/issue/comment/issue_history tools should NOT be called
        called_tools = {x["tool"] for x in captured_args}
        assert "asoc_list_projects" not in called_tools
        assert "asoc_list_layers" not in called_tools
        assert "asoc_list_issues" not in called_tools

        # All called tools should carry updated_after
        for entry in captured_args:
            assert "updated_after" in entry["args"], f"Tool {entry['tool']} missing updated_after"


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_mcp_auth_error_raises_connector_error(self) -> None:
        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            raise McpAuthError("bad token")

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        with pytest.raises(ConnectorError, match="auth_error"):
            await c.fetch("ws-1")

    async def test_mcp_unavailable_raises_connector_error(self) -> None:
        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            raise McpUnavailableError("server down")

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        with pytest.raises(ConnectorError, match="unavailable"):
            await c.fetch("ws-1")

    async def test_connector_not_configured_raises(self) -> None:
        c = AsocConnector()
        with pytest.raises(ConnectorError, match="not configured"):
            await c.fetch("ws-1")

    async def test_per_issue_error_is_warned_and_continued(self) -> None:
        """Error on per-issue fan-out emits a warning but does not abort fetch."""
        issues = [_raw_issue("i-1")]

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            if tool_name == "asoc_list_issues":
                return _list_result(issues)
            if tool_name == "asoc_get_issue_comments":
                raise McpUnavailableError("comments unavailable")
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        # Should NOT raise — error on comment fan-out is caught and logged
        docs = await c.fetch("ws-1")
        comment_docs = [d for d in docs if d.metadata.get("entity_type") == "comment"]
        assert comment_docs == []


# ---------------------------------------------------------------------------
# TestHealthCheck
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_with_mcp_client_returns_true(self) -> None:
        c = await _make_configured_connector(_make_mcp_client())
        result = await c.health_check()
        assert result is True

    async def test_not_configured_returns_false(self) -> None:
        c = AsocConnector()
        result = await c.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# TestAdminModeInvoke
# ---------------------------------------------------------------------------


class TestAdminModeInvoke:
    async def test_invoke_uses_empty_session_id(self) -> None:
        """Admin-mode MCP calls must pass session_id='' (no user session)."""
        captured: list[str] = []

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            captured.append(session_id)
            return _list_result([_raw_project()])

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        await c.fetch("ws-1")

        # All calls must use empty session_id (admin mode)
        assert all(s == "" for s in captured), f"Unexpected session_ids: {captured}"

    async def test_project_id_passed_to_list_tools(self) -> None:
        """project_id derived from config is passed as argument to list tools."""
        captured_args: list[dict] = []

        def _dispatch(
            session_id: str, tool_name: str, arguments: dict[str, Any]
        ) -> AsocToolCallResult:
            captured_args.append({"tool": tool_name, "args": dict(arguments)})
            return _empty_list_result()

        mcp = _make_mcp_client(invoke_side_effect=_dispatch)
        c = await _make_configured_connector(mcp)
        await c.fetch("ws-1")

        for entry in captured_args:
            # Per-issue tools may not have project_id if the issue list is empty
            if entry["tool"] not in ("asoc_get_issue_comments", "asoc_get_issue_history"):
                assert entry["args"].get("project_id") == "proj-uuid-1", (
                    f"Tool {entry['tool']} missing project_id"
                )
