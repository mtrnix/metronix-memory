"""<relevant_knowledge> retrieval-only path (MTRNIX-372).

Reuses retrieval.fast_search (dense-only recall, no reranker, no graph, no LLM
synthesis) so the proxy stays fast. Formatting is defensive over fragment dicts.
"""

from __future__ import annotations

from typing import Any

_EXCERPT_CHARS = 240


def _fragment_text(frag: dict[str, Any]) -> str:
    return str(frag.get("text") or frag.get("content") or "")


def _fragment_title(frag: dict[str, Any]) -> str:
    return str(frag.get("title") or frag.get("doc_label") or "untitled")


def _fragment_url(frag: dict[str, Any]) -> str:
    return str(frag.get("url") or "")


def format_knowledge_fragments(frags: list[dict[str, Any]]) -> tuple[str, int]:
    """Return (formatted_block, count). Empty input -> ('', 0)."""
    if not frags:
        return "", 0
    lines: list[str] = []
    for frag in frags:
        title = _fragment_title(frag)
        url = _fragment_url(frag)
        excerpt = _fragment_text(frag)[:_EXCERPT_CHARS].replace("\n", " ").strip()
        header = f"- {title} — {url}" if url else f"- {title}"
        lines.append(f"{header}\n  {excerpt}")
    return "\n".join(lines), len(frags)
