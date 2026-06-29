"""HTML processing and conversion to Markdown.

Handles Confluence page content: decodes JSON payloads, extracts HTML
from body.storage.value, fixes encoding issues with ftfy, converts
to Markdown via markdownify, and normalizes the output text.
"""

from __future__ import annotations

import json
from html import unescape

import structlog
from ftfy import fix_text
from markdownify import markdownify as html_to_md

from metronix.core.utils import normalize_text

logger = structlog.get_logger()


def process_html(body: bytes | str) -> str:  # TODO: async migration
    """Process a Confluence page payload into clean Markdown.

    Pipeline:
    1. bytes|str -> str
    2. Parse JSON, extract HTML from body.storage.value
    3. Decode ``\\uXXXX`` sequences to unicode
    4. Fix mojibake via ftfy
    5. Convert HTML -> Markdown
    6. Normalize text (strip surrogates)

    Args:
        body: Raw message body (bytes or string). May be a JSON payload
            from Confluence/Airbyte or raw HTML.

    Returns:
        Cleaned Markdown text.
    """
    raw_text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body

    # Try parsing as JSON (Airbyte format)
    html_content = raw_text
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            # Extract HTML from body.storage.value
            html_content = data.get("body", {}).get("storage", {}).get("value", "")
            if not html_content:
                # Fallback to body.view.value
                html_content = data.get("body", {}).get("view", {}).get("value", "")
            if not html_content:
                # If no body, use title as fallback
                html_content = f"<h1>{data.get('title', 'Untitled')}</h1>"
    except (json.JSONDecodeError, TypeError):
        pass  # Not JSON — use as is

    # Decode \uXXXX -> real unicode
    decoded = unescape(html_content)
    try:  # noqa: SIM105
        decoded = decoded.encode("utf-8").decode("unicode_escape")
    except Exception:
        pass  # If decoding error — keep as is

    # ftfy fixes mojibake like e.g. curly quotes
    decoded = fix_text(decoded)

    # HTML -> Markdown
    markdown_text = html_to_md(decoded, heading_style="ATX").strip()

    # Clean problematic characters
    markdown_text = normalize_text(markdown_text)

    logger.debug("html.processed", length=len(markdown_text))
    return markdown_text
