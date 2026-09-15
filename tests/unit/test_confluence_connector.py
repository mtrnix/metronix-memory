"""Tests for connectors/confluence_processing.py and ConfluenceConnector interface."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metronix.connectors.confluence import ConfluenceConnector, _iter_pages
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
        connector._client.get_content = MagicMock(
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
        connector._client.get_content = MagicMock(
            return_value=_page("100", "2026-05-12T22:09:28.000Z")
        )

        docs = connector._fetch_incremental(
            workspace_id="ws1",
            base_url="https://co.atlassian.net",
            space_key="X",
            since=since,
        )
        assert len(docs) == 1


# ---------------------------------------------------------------------------
# Cloud incremental sync — get_content portable path (#468)
# ---------------------------------------------------------------------------


class TestConfluenceFetchIncrementalCloud:
    def test_cloud_client_without_get_page_by_id_uses_get_content(self) -> None:
        """Cloud has cql + get_content but no get_page_by_id (atlassian-python-api 5.x)."""
        from datetime import UTC, datetime

        connector = ConfluenceConnector()
        connector._config = {
            "url": "https://co.atlassian.net",
            "space_key": "X",
            "username": "u",
            "api_token": "t",
        }
        since = datetime(2026, 1, 1, tzinfo=UTC)

        # Mirror Cloud: cql present, get_page_by_id absent; get_content is the portable API.
        client = MagicMock(spec=["cql", "get_content"])
        client.cql.return_value = {
            "results": [{"content": {"id": "100"}}],
            "totalSize": 1,
            "size": 1,
        }
        client.get_content.return_value = _page("100", "2026-05-12T22:09:28.000Z")
        connector._client = client

        docs = connector._fetch_incremental(
            workspace_id="ws1",
            base_url="https://co.atlassian.net",
            space_key="X",
            since=since,
        )

        assert len(docs) == 1
        assert docs[0].source_id == "100"
        client.get_content.assert_called_once_with(
            "100",
            expand="body.storage,version,history",
        )
        assert not hasattr(client, "get_page_by_id")


# ---------------------------------------------------------------------------
# _iter_pages — normalise get_all_pages_from_space across library majors (#460)
# ---------------------------------------------------------------------------


class TestIterPages:
    def test_list_passes_through(self) -> None:
        assert list(_iter_pages([{"id": "1"}, {"id": "2"}])) == [{"id": "1"}, {"id": "2"}]

    def test_generator_passes_through(self) -> None:
        gen = (p for p in [{"id": "1"}, {"id": "2"}])
        assert list(_iter_pages(gen)) == [{"id": "1"}, {"id": "2"}]

    def test_results_dict_is_unwrapped(self) -> None:
        assert list(_iter_pages({"results": [{"id": "1"}], "size": 1})) == [{"id": "1"}]

    def test_dict_without_results_is_empty(self) -> None:
        assert list(_iter_pages({"size": 0})) == []

    def test_none_is_empty(self) -> None:
        assert list(_iter_pages(None)) == []


# ---------------------------------------------------------------------------
# _fetch_full — must not call len() on the 5.x paginator (#460)
# ---------------------------------------------------------------------------


class TestConfluenceFetchFull:
    @staticmethod
    def _connector() -> ConfluenceConnector:
        c = ConfluenceConnector()
        c._config = {
            "url": "https://co.atlassian.net",
            "space_key": "ENG",
            "username": "u",
            "api_token": "t",
        }
        c._client = MagicMock()
        return c

    def _run(self, connector: ConfluenceConnector, space_key: str = "ENG") -> list:
        return connector._fetch_full(
            workspace_id="ws1",
            base_url="https://co.atlassian.net",
            space_key=space_key,
        )

    def test_generator_result_is_fully_consumed(self) -> None:
        """atlassian-python-api 5.x returns a generator — the #460 crash case."""
        connector = self._connector()
        connector._client.get_all_pages_from_space.return_value = (
            _page(str(i), "2026-05-12T22:09:28.000Z") for i in range(3)
        )

        docs = self._run(connector)

        assert [d.source_id for d in docs] == ["0", "1", "2"]
        # one call, no per-page start/limit paging
        connector._client.get_all_pages_from_space.assert_called_once()

    def test_list_result_still_works(self) -> None:
        """<= 4.x returned a list — the normaliser keeps that path working."""
        connector = self._connector()
        connector._client.get_all_pages_from_space.return_value = [
            _page("10", "2026-05-12T22:09:28.000Z"),
            _page("11", "2026-05-12T22:09:28.000Z"),
        ]

        docs = self._run(connector)

        assert [d.source_id for d in docs] == ["10", "11"]

    def test_empty_generator_yields_no_documents(self) -> None:
        connector = self._connector()
        connector._client.get_all_pages_from_space.return_value = iter(())

        assert self._run(connector) == []

    def test_dict_result_is_unwrapped(self) -> None:
        connector = self._connector()
        connector._client.get_all_pages_from_space.return_value = {
            "results": [_page("20", "2026-05-12T22:09:28.000Z")],
        }

        docs = self._run(connector)
        assert [d.source_id for d in docs] == ["20"]

    def test_one_bad_page_does_not_abort_the_batch(self) -> None:
        connector = self._connector()
        connector._client.get_all_pages_from_space.return_value = iter(
            [
                _page("30", "2026-05-12T22:09:28.000Z"),
                None,  # a malformed page — _page_to_document raises on .get()
                _page("32", "2026-05-12T22:09:28.000Z"),
            ]
        )

        docs = self._run(connector)
        assert [d.source_id for d in docs] == ["30", "32"]

    def test_no_space_key_passes_none(self) -> None:
        connector = self._connector()
        connector._client.get_all_pages_from_space.return_value = iter(())

        self._run(connector, space_key="")

        args, kwargs = connector._client.get_all_pages_from_space.call_args
        assert args[0] is None

    def test_rate_limit_mid_stream_propagates(self) -> None:
        """The 5.x paginator cannot be resumed after a sleep — a 429 fails the sync."""
        connector = self._connector()

        def _boom() -> object:
            yield _page("40", "2026-05-12T22:09:28.000Z")
            raise RuntimeError("429 Too Many Requests")

        connector._client.get_all_pages_from_space.return_value = _boom()

        with pytest.raises(RuntimeError, match="429"):
            self._run(connector)


# ---------------------------------------------------------------------------
# The atlassian client is blocking `requests`; every call must run off the
# event loop so a slow/hung Confluence can't freeze the API (#459).
# ---------------------------------------------------------------------------


def _thread_recorder(seen: list[object], return_value: object):
    import threading

    def _record(*_a: object, **_k: object) -> object:
        seen.append(threading.current_thread())
        return return_value

    return _record


class TestConfluenceRunsOffTheEventLoop:
    @staticmethod
    def _connector() -> ConfluenceConnector:
        c = ConfluenceConnector()
        c._config = {
            "url": "https://co.atlassian.net",
            "space_key": "ENG",
            "username": "u",
            "api_token": "t",
        }
        c._client = MagicMock()
        return c

    @pytest.mark.asyncio
    async def test_full_fetch_offloads_get_all_pages_from_space(self) -> None:
        import threading

        connector = self._connector()
        seen: list[object] = []
        connector._client.get_all_pages_from_space.side_effect = _thread_recorder(seen, iter(()))

        await connector.fetch("ws1", since=None)

        assert seen and seen[0] is not threading.main_thread()

    @pytest.mark.asyncio
    async def test_incremental_fetch_offloads_cql(self) -> None:
        import threading
        from datetime import UTC, datetime

        connector = self._connector()
        seen: list[object] = []
        connector._client.cql.side_effect = _thread_recorder(
            seen, {"results": [], "totalSize": 0, "size": 0}
        )

        await connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC))

        assert seen and seen[0] is not threading.main_thread()

    @pytest.mark.asyncio
    async def test_health_check_offloads_get_all_spaces(self) -> None:
        import threading

        connector = self._connector()
        seen: list[object] = []
        connector._client.get_all_spaces.side_effect = _thread_recorder(seen, [])

        assert await connector.health_check() is True
        assert seen and seen[0] is not threading.main_thread()
