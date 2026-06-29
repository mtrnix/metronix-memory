"""Tests for connectors/confluence_processing.py and ConfluenceConnector interface."""

from __future__ import annotations

import pytest

from metronix.connectors.confluence import ConfluenceConnector
from metronix.connectors.confluence_processing import process_confluence_page
from metronix.connectors.jira import JiraConnector
from metronix.core.interfaces import ConnectorInterface


class TestProcessConfluencePage:
    def test_basic_html_to_markdown(self) -> None:
        html = "<h1>Welcome</h1><p>This is a test page.</p>"
        title, content = process_confluence_page(html)
        assert title == "Welcome"
        assert "Welcome" in content
        assert "test page" in content

    def test_api_title_preferred(self) -> None:
        html = "<h1>Wrong Title</h1><p>Body text.</p>"
        title, content = process_confluence_page(html, page_title="Correct Title")
        assert title == "Correct Title"

    def test_title_prepended_as_h1(self) -> None:
        html = "<p>Just a paragraph without heading.</p>"
        title, content = process_confluence_page(html, page_title="My Page")
        assert title == "My Page"
        assert content.lstrip().startswith("# My Page")

    def test_empty_html(self) -> None:
        title, content = process_confluence_page("", page_title="Empty")
        assert title == "Empty"

    def test_complex_html(self) -> None:
        html = """
        <h1>Architecture</h1>
        <p>The system uses <strong>microservices</strong>.</p>
        <ul>
            <li>Service A</li>
            <li>Service B</li>
        </ul>
        <table>
            <tr><th>Name</th><th>Port</th></tr>
            <tr><td>API</td><td>8080</td></tr>
        </table>
        """
        title, content = process_confluence_page(html)
        assert title == "Architecture"
        assert "microservices" in content
        assert "Service A" in content


class TestConnectorInterface:
    def test_confluence_implements_interface(self) -> None:
        connector = ConfluenceConnector()
        assert isinstance(connector, ConnectorInterface)

    def test_jira_implements_interface(self) -> None:
        connector = JiraConnector()
        assert isinstance(connector, ConnectorInterface)

    def test_confluence_has_required_methods(self) -> None:
        connector = ConfluenceConnector()
        assert hasattr(connector, "configure")
        assert hasattr(connector, "fetch")
        assert hasattr(connector, "health_check")
        assert callable(connector.configure)
        assert callable(connector.fetch)
        assert callable(connector.health_check)

    def test_jira_has_required_methods(self) -> None:
        connector = JiraConnector()
        assert hasattr(connector, "configure")
        assert hasattr(connector, "fetch")
        assert hasattr(connector, "health_check")

    @pytest.mark.asyncio
    async def test_confluence_health_check_unconfigured(self) -> None:
        connector = ConfluenceConnector()
        assert await connector.health_check() is False

    @pytest.mark.asyncio
    async def test_jira_health_check_unconfigured(self) -> None:
        connector = JiraConnector()
        assert await connector.health_check() is False

    @pytest.mark.asyncio
    async def test_confluence_fetch_unconfigured_raises(self) -> None:
        connector = ConfluenceConnector()
        with pytest.raises(RuntimeError, match="not configured"):
            await connector.fetch("ws1")

    @pytest.mark.asyncio
    async def test_jira_fetch_unconfigured_raises(self) -> None:
        connector = JiraConnector()
        with pytest.raises(RuntimeError, match="not configured"):
            await connector.fetch("ws1")


class TestConnectorRegistry:
    def test_registry_has_confluence_and_jira(self) -> None:
        from metronix.connectors.registry import ConnectorRegistry, register_builtins

        registry = ConnectorRegistry()
        register_builtins(registry)
        assert registry.is_registered("confluence")
        assert registry.is_registered("jira")

    def test_registry_creates_confluence(self) -> None:
        from metronix.connectors.registry import ConnectorRegistry, register_builtins

        registry = ConnectorRegistry()
        register_builtins(registry)
        connector = registry.create("confluence")
        assert isinstance(connector, ConfluenceConnector)

    def test_registry_creates_jira(self) -> None:
        from metronix.connectors.registry import ConnectorRegistry, register_builtins

        registry = ConnectorRegistry()
        register_builtins(registry)
        connector = registry.create("jira")
        assert isinstance(connector, JiraConnector)


# ---------------------------------------------------------------------------
# Sub-minute post-filter (PROJ-332) — parity with Jira
# ---------------------------------------------------------------------------


def _page(page_id: str, when: str) -> dict:
    """Minimal Confluence page payload that survives _page_to_document."""
    return {
        "id": page_id,
        "title": f"Page {page_id}",
        "body": {"storage": {"value": f"<p>body {page_id}</p>"}},
        "version": {"when": when, "by": {"displayName": "u"}},
        "_links": {"webui": f"/spaces/X/pages/{page_id}"},
    }


class TestConfluenceFetchPostFilter:
    @pytest.mark.asyncio
    async def test_drops_page_with_version_when_equal_to_since(self) -> None:
        """CQL minute-precision lets same-minute pages through; post-filter drops them."""
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        connector = ConfluenceConnector()
        connector._config = {
            "url": "https://co.atlassian.net",
            "space_key": "X",
            "username": "u",
            "api_token": "t",
        }
        since = datetime(2026, 5, 12, 22, 9, 27, tzinfo=UTC)

        connector._client = MagicMock()
        connector._client.cql = MagicMock(
            return_value={
                "results": [{"content": {"id": "100"}}],
                "totalSize": 1,
                "size": 1,
            }
        )
        connector._client.get_page_by_id = MagicMock(
            return_value=_page("100", "2026-05-12T22:09:27.000Z")
        )

        # _fetch_incremental is sync; call directly.
        docs = connector._fetch_incremental(
            workspace_id="ws1",
            base_url="https://co.atlassian.net",
            space_key="X",
            since=since,
        )
        assert docs == [], "page with version.when == since must be filtered out"

    @pytest.mark.asyncio
    async def test_keeps_page_with_version_when_after_since(self) -> None:
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        connector = ConfluenceConnector()
        connector._config = {
            "url": "https://co.atlassian.net",
            "space_key": "X",
            "username": "u",
            "api_token": "t",
        }
        since = datetime(2026, 5, 12, 22, 9, 27, tzinfo=UTC)

        connector._client = MagicMock()
        connector._client.cql = MagicMock(
            return_value={
                "results": [{"content": {"id": "100"}}],
                "totalSize": 1,
                "size": 1,
            }
        )
        connector._client.get_page_by_id = MagicMock(
            return_value=_page("100", "2026-05-12T22:09:28.000Z")
        )

        docs = connector._fetch_incremental(
            workspace_id="ws1",
            base_url="https://co.atlassian.net",
            space_key="X",
            since=since,
        )
        assert len(docs) == 1
