"""Confluence page processing — HTML extraction and text preparation.

Reuses existing ingestion processors to convert Confluence page payloads
into clean text ready for the Document.content field.
"""

from __future__ import annotations

import structlog

from metatron.ingestion.processors.html import process_html
from metatron.ingestion.processors.titles import extract_title_from_markdown

logger = structlog.get_logger()


def process_confluence_page(
    page_body_html: str,
    page_title: str | None = None,
) -> tuple[str, str]:
    """Convert Confluence page HTML into clean Markdown text.

    Pipeline:
    1. HTML → Markdown via process_html (ftfy + markdownify)
    2. Extract or prepend title
    3. Return (title, content)

    Args:
        page_body_html: Raw HTML from page body.storage.value.
        page_title: Title from API (preferred over extraction).

    Returns:
        (title, markdown_content) tuple.
    """
    markdown = process_html(page_body_html)

    if page_title:
        title = page_title
    else:
        title = extract_title_from_markdown(markdown)

    # Prepend title as H1 if not already present
    if markdown and not markdown.lstrip().startswith(f"# {title}"):
        markdown = f"# {title}\n\n{markdown}"

    logger.debug("confluence.page.processed", title=title, length=len(markdown))
    return title, markdown
