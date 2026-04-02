"""Notion block processing — recursive block-to-markdown conversion.

Converts Notion API block objects into clean Markdown text.
Handles pagination for child blocks and skips child_page/child_database
content to avoid duplication (they are fetched as separate pages).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from notion_client import AsyncClient

logger = structlog.get_logger()

_RATE_LIMIT_DELAY = 4
_MAX_BLOCK_DEPTH = 5


async def fetch_all_blocks(client: AsyncClient, page_id: str) -> list[dict]:
    """Fetch all blocks from a page/block, handling pagination."""
    all_blocks: list[dict] = []
    cursor = None
    while True:
        try:
            resp = await client.blocks.children.list(
                block_id=page_id,
                start_cursor=cursor,
                page_size=100,
            )
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                logger.warning("notion.blocks.rate_limit", block_id=page_id)
                await asyncio.sleep(_RATE_LIMIT_DELAY)
                continue
            raise
        all_blocks.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return all_blocks


def _rich_text_to_str(rich_text: list[dict]) -> str:
    """Extract plain text from Notion rich_text array."""
    return "".join(t.get("plain_text", "") for t in rich_text)


async def blocks_to_markdown(
    client: AsyncClient,
    blocks: list[dict],
    title: str | None = None,
    _depth: int = 0,
) -> str:
    """Convert Notion blocks to Markdown, recursing into children.

    Skips child_page/child_database block content to avoid duplication
    (those pages are fetched separately), but includes their titles.

    Args:
        client: Notion async client (for fetching nested children).
        blocks: List of block dicts from the Notion API.
        title: Page title to prepend as H1 (only at top level).
        _depth: Current recursion depth (internal, do not set).

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    # Prepend title as H1 at top level (like confluence_processing)
    if title and _depth == 0:
        lines.append(f"# {title}")

    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        text = _rich_text_to_str(data.get("rich_text", []))

        if btype == "paragraph":
            lines.append(text)
        elif btype.startswith("heading_"):
            level = int(btype[-1])
            lines.append(f"{'#' * level} {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"- {text}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {text}")
        elif btype == "to_do":
            checked = "x" if data.get("checked") else " "
            lines.append(f"- [{checked}] {text}")
        elif btype == "toggle":
            lines.append(f"<details><summary>{text}</summary></details>")
        elif btype == "code":
            lang = data.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif btype == "quote":
            lines.append(f"> {text}")
        elif btype == "divider":
            lines.append("---")
        elif btype == "callout":
            icon = data.get("icon", {}).get("emoji", "")
            lines.append(f"> {icon} {text}")
        elif btype == "table_row":
            cells = data.get("cells", [])
            row = " | ".join(_rich_text_to_str(cell) for cell in cells)
            lines.append(f"| {row} |")
        elif btype == "child_page":
            child_title = data.get("title", "(untitled)")
            lines.append(f"- 📄 [{child_title}]")
        elif btype == "child_database":
            child_title = data.get("title", "(untitled database)")
            lines.append(f"- 🗃 [{child_title}]")
        elif text:
            lines.append(text)

        # Recurse into children (but NOT child_page/child_database, and respect max depth)
        if (
            block.get("has_children")
            and btype not in ("child_page", "child_database")
            and _depth < _MAX_BLOCK_DEPTH
        ):
            try:
                children = await fetch_all_blocks(client, block["id"])
                child_md = await blocks_to_markdown(client, children, _depth=_depth + 1)
                if child_md.strip():
                    lines.append(child_md)
            except Exception as exc:
                logger.warning(
                    "notion.blocks.children_error", block_id=block["id"], error=str(exc)
                )

    return "\n\n".join(lines)


def get_page_title(page: dict) -> str:
    """Extract title from a Notion page object."""
    for prop_val in page.get("properties", {}).values():
        if prop_val.get("type") == "title":
            return _rich_text_to_str(prop_val.get("title", []))
    return ""
