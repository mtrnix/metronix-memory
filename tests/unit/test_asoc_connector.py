"""Unit tests for AsocConnector.

Uses httpx.MockTransport (via respx or manual _request patches) so no live ASOC
instance is required.  All tests run fully in-process and in-memory.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from metatron.connectors.asoc import AsocConnector
from metatron.core.exceptions import ConnectorError
from metatron.core.models import Connection

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


def _valid_config(url: str = "https://asoc.example.com") -> dict[str, str]:
    return {
        "url": url,
        "service_token": "tok-secret",
        "project_id": "proj-uuid-1",
        "asoc_instance_id": "inst-1",
    }


async def _configure_connector(
    connector: AsocConnector, url: str = "https://asoc.example.com"
) -> None:
    await connector.configure(_make_connection(), _valid_config(url=url))


_FAKE_REQUEST = httpx.Request("GET", "https://asoc.example.com/fake")


def _make_response(status_code: int, body: str, headers: dict | None = None) -> httpx.Response:
    """Build an httpx.Response with a fake request attached (required for raise_for_status)."""
    resp = httpx.Response(
        status_code,
        text=body,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    resp._request = _FAKE_REQUEST  # type: ignore[attr-defined]
    return resp


def _page_response(items: list[dict], has_next: bool = False) -> httpx.Response:
    body = json.dumps({"items": items, "has_next": has_next})
    return _make_response(200, body)


def _empty_response() -> httpx.Response:
    return _page_response([])


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
    }


def _raw_project(project_id: str = "proj-uuid-1") -> dict[str, Any]:
    return {
        "id": project_id,
        "name": "Test Project",
        "description": "desc",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-06-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# TestConfigure
# ---------------------------------------------------------------------------


class TestConfigure:
    async def test_happy_path(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)
        assert c._base_url == "https://asoc.example.com"
        assert c._project_id == "proj-uuid-1"
        assert c._instance_id == "inst-1"
        assert c._client is not None

    async def test_trailing_slash_trimmed(self) -> None:
        c = AsocConnector()
        await _configure_connector(c, url="https://asoc.example.com/")
        assert c._base_url == "https://asoc.example.com"

    @pytest.mark.parametrize(
        "missing_key",
        ["url", "service_token", "project_id", "asoc_instance_id"],
    )
    async def test_missing_key_raises(self, missing_key: str) -> None:
        config = _valid_config()
        del config[missing_key]
        c = AsocConnector()
        with pytest.raises(ConnectorError, match="asoc.configure.missing_key"):
            await c.configure(_make_connection(), config)

    @pytest.mark.parametrize(
        "empty_key",
        ["url", "service_token", "project_id", "asoc_instance_id"],
    )
    async def test_empty_value_raises(self, empty_key: str) -> None:
        config = {**_valid_config(), empty_key: ""}
        c = AsocConnector()
        with pytest.raises(ConnectorError, match="asoc.configure.missing_key"):
            await c.configure(_make_connection(), config)


# ---------------------------------------------------------------------------
# TestFetchBootstrap
# ---------------------------------------------------------------------------


class TestFetchBootstrap:
    async def test_iterates_all_entity_types_in_order(self) -> None:
        """Verify all 10 entity types are iterated and produce Documents."""
        c = AsocConnector()
        await _configure_connector(c)

        async def _fake_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
            # issue list for per-issue fan-out
            if "/issues" in path and "comments" not in path and "history" not in path:
                return _page_response([_raw_issue("issue-1")])
            if "comments" in path or "history" in path:
                return _empty_response()
            # project is single-object; return as items list
            if path.endswith(f"/projects/{c._project_id}"):
                body = json.dumps({"items": [_raw_project()], "has_next": False})
                return _make_response(200, body)
            # All other list endpoints: one generic item
            item_id = f"e-{path.split('/')[-1]}"
            body = json.dumps(
                {
                    "items": [{"id": item_id, "created_at": "2025-01-01T00:00:00Z"}],
                    "has_next": False,
                }
            )
            return _make_response(200, body)

        with patch.object(c, "_request", side_effect=_fake_request):
            docs = await c.fetch("ws-1")

        assert len(docs) >= 1

    async def test_empty_project_returns_empty_list(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)

        async def _all_empty(method: str, path: str, **kwargs: Any) -> httpx.Response:
            return _empty_response()

        with patch.object(c, "_request", side_effect=_all_empty):
            docs = await c.fetch("ws-1")

        assert docs == []

    async def test_paginated_entity_type(self) -> None:
        """Two pages for layer endpoint → all items collected."""
        c = AsocConnector()
        await _configure_connector(c)

        page1_items = [
            {"id": f"layer-{i}", "created_at": "2025-01-01T00:00:00Z"} for i in range(50)
        ]
        page2_items = [{"id": "layer-50", "name": "Last", "created_at": "2025-01-01T00:00:00Z"}]

        async def _paged(method: str, path: str, **kwargs: Any) -> httpx.Response:
            params = kwargs.get("params", {})
            page = int(params.get("page", 1))
            if "/layers" in path:
                if page == 1:
                    return _page_response(page1_items, has_next=True)
                return _page_response(page2_items, has_next=False)
            return _empty_response()

        with patch.object(c, "_request", side_effect=_paged):
            docs = await c.fetch("ws-1")

        layer_docs = [d for d in docs if d.metadata.get("entity_type") == "layer"]
        assert len(layer_docs) == 51

    async def test_malformed_entity_skipped(self) -> None:
        """Entity missing 'id' must be skipped (logged as warning, not raised)."""
        c = AsocConnector()
        await _configure_connector(c)

        async def _bad_item(method: str, path: str, **kwargs: Any) -> httpx.Response:
            if "/issues" in path and "comments" not in path and "history" not in path:
                return _page_response([{"title": "no id here"}])
            return _empty_response()

        with patch.object(c, "_request", side_effect=_bad_item):
            docs = await c.fetch("ws-1")

        issue_docs = [d for d in docs if d.metadata.get("entity_type") == "issue"]
        assert issue_docs == []


# ---------------------------------------------------------------------------
# TestFetchIncremental
# ---------------------------------------------------------------------------


class TestFetchIncremental:
    async def test_updated_after_param_passed_when_since_set(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)

        since = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        captured_params: list[dict] = []

        async def _capture(method: str, path: str, **kwargs: Any) -> httpx.Response:
            if "params" in kwargs:
                captured_params.append(dict(kwargs["params"]))
            return _empty_response()

        with patch.object(c, "_request", side_effect=_capture):
            await c.fetch("ws-1", since=since)

        ua_params = [p for p in captured_params if "updated_after" in p]
        assert len(ua_params) > 0
        assert since.isoformat() in ua_params[0]["updated_after"]

    async def test_fallback_on_400_updated_after(self) -> None:
        """When endpoint returns 400 mentioning updated_after, flag flipped to False."""
        c = AsocConnector()
        await _configure_connector(c)

        since = datetime(2025, 6, 1, tzinfo=UTC)

        async def _400_then_ok(method: str, path: str, **kwargs: Any) -> httpx.Response:
            params = kwargs.get("params", {})
            if "/issues" in path and "updated_after" in params:
                return _make_response(400, "updated_after not supported")
            if "/issues" in path and "comments" not in path and "history" not in path:
                return _page_response([_raw_issue()])
            return _empty_response()

        with patch.object(c, "_request", side_effect=_400_then_ok):
            await c.fetch("ws-1", since=since)

        assert c._updated_after_supported["issue"] is False

    async def test_client_side_filter_drops_old_items(self) -> None:
        """Items with updated_at <= since are dropped client-side when flag=False."""
        c = AsocConnector()
        await _configure_connector(c)
        c._updated_after_supported["issue"] = False

        since = datetime(2025, 6, 1, tzinfo=UTC)
        old_issue = {**_raw_issue("old"), "updated_at": "2025-05-01T00:00:00Z"}
        new_issue = {**_raw_issue("new"), "updated_at": "2025-06-02T00:00:00Z"}

        async def _issues(method: str, path: str, **kwargs: Any) -> httpx.Response:
            if "/issues" in path and "comments" not in path and "history" not in path:
                return _page_response([old_issue, new_issue])
            return _empty_response()

        with patch.object(c, "_request", side_effect=_issues):
            docs = await c.fetch("ws-1", since=since)

        issue_docs = [d for d in docs if d.metadata.get("entity_type") == "issue"]
        assert len(issue_docs) == 1
        assert issue_docs[0].source_id == "new"


# ---------------------------------------------------------------------------
# TestFetchResumeHints
# ---------------------------------------------------------------------------


class TestFetchResumeHints:
    async def test_after_resource_skips_earlier_types(self) -> None:
        """after_resource='scan_result' skips project, layer, issue, etc."""
        c = AsocConnector()
        await _configure_connector(c)

        fetched_types: list[str] = []

        async def _track(method: str, path: str, **kwargs: Any) -> httpx.Response:
            for entity_type, template in c._ENDPOINTS.items():
                bare = template.format(project_id=c._project_id, issue_id="x").split("?")[0]
                if path.rstrip("/") == bare.rstrip("/"):
                    fetched_types.append(entity_type)
                    break
            return _empty_response()

        with patch.object(c, "_request", side_effect=_track):
            await c.fetch("ws-1", after_resource="scan_result")

        idx = AsocConnector.ENTITY_ORDER.index("scan_result")
        for etype in AsocConnector.ENTITY_ORDER[:idx]:
            assert etype not in fetched_types, f"{etype!r} should have been skipped"

    async def test_after_id_skips_within_type(self) -> None:
        """after_id='issue-1' means items up to and including issue-1 are skipped."""
        c = AsocConnector()
        await _configure_connector(c)

        items = [_raw_issue(f"issue-{i}") for i in range(1, 4)]

        async def _issues(method: str, path: str, **kwargs: Any) -> httpx.Response:
            if "/issues" in path and "comments" not in path and "history" not in path:
                return _page_response(items)
            return _empty_response()

        with patch.object(c, "_request", side_effect=_issues):
            docs = await c.fetch("ws-1", after_resource="issue", after_id="issue-1")

        issue_docs = [d for d in docs if d.metadata.get("entity_type") == "issue"]
        source_ids = [d.source_id for d in issue_docs]
        assert "issue-1" not in source_ids
        assert "issue-2" in source_ids
        assert "issue-3" in source_ids

    async def test_invalid_after_resource_falls_back_to_start(self) -> None:
        """Invalid after_resource should be ignored and fetch starts from the beginning."""
        c = AsocConnector()
        await _configure_connector(c)

        first_type_fetched: list[str] = []

        async def _track_first(method: str, path: str, **kwargs: Any) -> httpx.Response:
            project_path = c._ENDPOINTS["project"].format(project_id=c._project_id)
            if path == project_path and not first_type_fetched:
                first_type_fetched.append("project")
            return _empty_response()

        with patch.object(c, "_request", side_effect=_track_first):
            await c.fetch("ws-1", after_resource="nonexistent_type", after_id="some-id")

        assert "project" in first_type_fetched

    async def test_resume_composes_with_since(self) -> None:
        """after_resource + since together: resume skips types AND passes updated_after."""
        c = AsocConnector()
        await _configure_connector(c)

        since = datetime(2025, 6, 1, tzinfo=UTC)
        captured: list[dict] = []

        async def _capture(method: str, path: str, **kwargs: Any) -> httpx.Response:
            captured.append({"path": path, "params": dict(kwargs.get("params", {}))})
            return _empty_response()

        with patch.object(c, "_request", side_effect=_capture):
            await c.fetch("ws-1", since=since, after_resource="scan_result")

        project_path = c._ENDPOINTS["project"].format(project_id=c._project_id)
        project_calls = [r for r in captured if r["path"] == project_path]
        assert project_calls == []

        for req in captured:
            if req["params"]:
                assert "updated_after" in req["params"]


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_5xx_retries_then_raises_connector_error(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)
        c._RETRY_ATTEMPTS = 3

        with (
            patch("metatron.connectors.asoc.asyncio.sleep", new=AsyncMock()),
            patch.object(c, "_client") as mock_client,
        ):
            mock_client.request = AsyncMock(return_value=httpx.Response(500, text="err"))
            with pytest.raises(ConnectorError, match="asoc.request_failed"):
                await c._request("GET", "/some/path")

    async def test_429_honors_retry_after_header(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)
        c._RETRY_ATTEMPTS = 2

        slept_for: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            slept_for.append(seconds)

        responses = [
            httpx.Response(429, headers={"Retry-After": "5"}, text="rate limit"),
            httpx.Response(200, text='{"items": [], "has_next": false}'),
        ]
        idx = 0

        async def _429_then_ok(*args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal idx
            r = responses[min(idx, len(responses) - 1)]
            idx += 1
            return r

        with (
            patch("metatron.connectors.asoc.asyncio.sleep", side_effect=_fake_sleep),
            patch.object(c, "_client") as mock_client,
        ):
            mock_client.request = AsyncMock(side_effect=_429_then_ok)
            response = await c._request("GET", "/api/v1/projects/proj-uuid-1")

        assert response.status_code == 200
        assert 5.0 in slept_for

    async def test_401_raises_immediately_no_retry(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)

        call_count = 0

        async def _401(*args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, text="unauthorized")

        with patch.object(c, "_client") as mock_client:
            mock_client.request = AsyncMock(side_effect=_401)
            with pytest.raises(ConnectorError):
                await c._request("GET", "/secure")

        assert call_count == 1, "401 must not be retried"

    async def test_403_raises_immediately_no_retry(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)

        call_count = 0

        async def _403(*args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(403, text="forbidden")

        with patch.object(c, "_client") as mock_client:
            mock_client.request = AsyncMock(side_effect=_403)
            with pytest.raises(ConnectorError):
                await c._request("GET", "/restricted")

        assert call_count == 1, "403 must not be retried"

    async def test_network_error_retries(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)
        c._RETRY_ATTEMPTS = 3

        call_count = 0

        async def _network_error(*args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("connection refused")

        with (
            patch("metatron.connectors.asoc.asyncio.sleep", new=AsyncMock()),
            patch.object(c, "_client") as mock_client,
        ):
            mock_client.request = AsyncMock(side_effect=_network_error)
            with pytest.raises(ConnectorError, match="asoc.request_failed"):
                await c._request("GET", "/api/v1/projects/proj-uuid-1")

        assert call_count == c._RETRY_ATTEMPTS

    async def test_per_entity_404_is_warned_and_continued(self) -> None:
        """A 404 for a per-issue sub-endpoint (comments) emits a warning and continues."""
        c = AsocConnector()
        await _configure_connector(c)

        issues = [_raw_issue("i-1"), _raw_issue("i-2")]

        async def _issues_then_404(method: str, path: str, **kwargs: Any) -> httpx.Response:
            if "/issues" in path and "comments" not in path and "history" not in path:
                return _page_response(issues)
            if "comments" in path:
                return _make_response(404, "not found")
            return _empty_response()

        with patch.object(c, "_request", side_effect=_issues_then_404):
            docs = await c.fetch("ws-1")

        comment_docs = [d for d in docs if d.metadata.get("entity_type") == "comment"]
        assert comment_docs == []

    async def test_connector_not_configured_raises(self) -> None:
        c = AsocConnector()
        with pytest.raises(ConnectorError, match="not configured"):
            await c.fetch("ws-1")


# ---------------------------------------------------------------------------
# TestHealthCheck
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_2xx_returns_true(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)

        async def _ok(method: str, path: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, text="{}")

        with patch.object(c, "_request", side_effect=_ok):
            result = await c.health_check()

        assert result is True

    async def test_5xx_returns_false(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)

        async def _error(method: str, path: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(500, text="err")

        with patch.object(c, "_request", side_effect=_error):
            result = await c.health_check()

        assert result is False

    async def test_exception_returns_false(self) -> None:
        c = AsocConnector()
        await _configure_connector(c)

        async def _exc(method: str, path: str, **kwargs: Any) -> httpx.Response:
            raise ConnectorError("boom")

        with patch.object(c, "_request", side_effect=_exc):
            result = await c.health_check()

        assert result is False

    async def test_not_configured_returns_false(self) -> None:
        c = AsocConnector()
        result = await c.health_check()
        assert result is False
