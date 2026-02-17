"""Tests for connectors/notion_processing.py and NotionConnector interface."""

from __future__ import annotations

import pytest

from metatron.connectors.notion import NotionConnector
from metatron.connectors.notion_processing import (
    _rich_text_to_str,
    blocks_to_markdown,
    get_page_title,
)
from metatron.core.interfaces import ConnectorInterface


class TestRichTextToStr:
    def test_empty_list(self) -> None:
        assert _rich_text_to_str([]) == ""

    def test_single_text(self) -> None:
        rt = [{"plain_text": "hello"}]
        assert _rich_text_to_str(rt) == "hello"

    def test_multiple_texts(self) -> None:
        rt = [{"plain_text": "hello "}, {"plain_text": "world"}]
        assert _rich_text_to_str(rt) == "hello world"

    def test_missing_plain_text_key(self) -> None:
        rt = [{"type": "text"}]
        assert _rich_text_to_str(rt) == ""


class TestGetPageTitle:
    def test_extracts_title(self) -> None:
        page = {
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "My Page"}],
                }
            }
        }
        assert get_page_title(page) == "My Page"

    def test_no_title_property(self) -> None:
        page = {"properties": {"Status": {"type": "select"}}}
        assert get_page_title(page) == ""

    def test_empty_properties(self) -> None:
        page = {"properties": {}}
        assert get_page_title(page) == ""

    def test_no_properties_key(self) -> None:
        page = {}
        assert get_page_title(page) == ""

    def test_multi_word_title(self) -> None:
        page = {
            "properties": {
                "Title": {
                    "type": "title",
                    "title": [
                        {"plain_text": "Project "},
                        {"plain_text": "Aurora"},
                    ],
                }
            }
        }
        assert get_page_title(page) == "Project Aurora"


def _make_block(btype: str, text: str = "", **extra) -> dict:
    """Helper to create a Notion block dict."""
    data = {"rich_text": [{"plain_text": text}]} if text else {"rich_text": []}
    data.update(extra)
    return {"type": btype, btype: data, "has_children": False}


class _FakeClient:
    """Minimal fake Notion client for testing blocks_to_markdown."""

    def __init__(self, children_map: dict[str, list[dict]] | None = None) -> None:
        self._children = children_map or {}

    class blocks:  # noqa: N801
        _outer = None

        class children:  # noqa: N801
            _outer = None

            @staticmethod
            async def list(block_id: str, start_cursor=None, page_size=100):
                # Access via closure isn't clean, so we use a class-level ref
                raise NotImplementedError

    async def _list_children(self, block_id: str, **kwargs):
        blocks = self._children.get(block_id, [])
        return {"results": blocks, "has_more": False}


class TestBlocksToMarkdown:
    @pytest.mark.asyncio
    async def test_paragraph(self) -> None:
        blocks = [_make_block("paragraph", "Hello world")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_heading_levels(self) -> None:
        blocks = [
            _make_block("heading_1", "Title"),
            _make_block("heading_2", "Subtitle"),
            _make_block("heading_3", "Section"),
        ]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "# Title" in result
        assert "## Subtitle" in result
        assert "### Section" in result

    @pytest.mark.asyncio
    async def test_bulleted_list(self) -> None:
        blocks = [_make_block("bulleted_list_item", "Item one")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "- Item one" in result

    @pytest.mark.asyncio
    async def test_numbered_list(self) -> None:
        blocks = [_make_block("numbered_list_item", "Step one")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "1. Step one" in result

    @pytest.mark.asyncio
    async def test_todo_checked(self) -> None:
        blocks = [_make_block("to_do", "Done task", checked=True)]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "- [x] Done task" in result

    @pytest.mark.asyncio
    async def test_todo_unchecked(self) -> None:
        blocks = [_make_block("to_do", "Pending task", checked=False)]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "- [ ] Pending task" in result

    @pytest.mark.asyncio
    async def test_code_block(self) -> None:
        blocks = [_make_block("code", "print('hi')", language="python")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "```python" in result
        assert "print('hi')" in result

    @pytest.mark.asyncio
    async def test_quote(self) -> None:
        blocks = [_make_block("quote", "Important note")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "> Important note" in result

    @pytest.mark.asyncio
    async def test_divider(self) -> None:
        blocks = [_make_block("divider")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "---" in result

    @pytest.mark.asyncio
    async def test_callout_with_emoji(self) -> None:
        blocks = [_make_block("callout", "Warning text", icon={"emoji": "⚠️"})]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "⚠️" in result
        assert "Warning text" in result

    @pytest.mark.asyncio
    async def test_child_page_title(self) -> None:
        blocks = [_make_block("child_page", title="Sub Page")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "Sub Page" in result

    @pytest.mark.asyncio
    async def test_child_database_title(self) -> None:
        blocks = [_make_block("child_database", title="My DB")]
        result = await blocks_to_markdown(_FakeClient(), blocks)
        assert "My DB" in result

    @pytest.mark.asyncio
    async def test_title_prepended_at_top_level(self) -> None:
        blocks = [_make_block("paragraph", "Body text")]
        result = await blocks_to_markdown(_FakeClient(), blocks, title="My Page")
        assert result.lstrip().startswith("# My Page")
        assert "Body text" in result

    @pytest.mark.asyncio
    async def test_title_not_prepended_at_depth(self) -> None:
        blocks = [_make_block("paragraph", "Nested")]
        result = await blocks_to_markdown(_FakeClient(), blocks, title="Ignored", _depth=1)
        assert not result.lstrip().startswith("# Ignored")

    @pytest.mark.asyncio
    async def test_empty_blocks(self) -> None:
        result = await blocks_to_markdown(_FakeClient(), [])
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_blocks_with_title(self) -> None:
        result = await blocks_to_markdown(_FakeClient(), [], title="Only Title")
        assert "# Only Title" in result


class TestNotionConnectorInterface:
    def test_implements_interface(self) -> None:
        connector = NotionConnector()
        assert isinstance(connector, ConnectorInterface)

    def test_has_required_methods(self) -> None:
        connector = NotionConnector()
        assert hasattr(connector, "configure")
        assert hasattr(connector, "fetch")
        assert hasattr(connector, "health_check")
        assert callable(connector.configure)
        assert callable(connector.fetch)
        assert callable(connector.health_check)

    @pytest.mark.asyncio
    async def test_health_check_unconfigured(self) -> None:
        connector = NotionConnector()
        assert await connector.health_check() is False

    @pytest.mark.asyncio
    async def test_fetch_unconfigured_raises(self) -> None:
        connector = NotionConnector()
        with pytest.raises(RuntimeError, match="not configured"):
            await connector.fetch("ws1")


class TestNotionConnectorRegistry:
    def test_registry_has_notion(self) -> None:
        from metatron.connectors.registry import ConnectorRegistry, register_builtins

        registry = ConnectorRegistry()
        register_builtins(registry)
        assert registry.is_registered("notion")

    def test_registry_creates_notion(self) -> None:
        from metatron.connectors.registry import ConnectorRegistry, register_builtins

        registry = ConnectorRegistry()
        register_builtins(registry)
        connector = registry.create("notion")
        assert isinstance(connector, NotionConnector)
