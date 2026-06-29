"""Inject the enrichment block into the outgoing messages (MTRNIX-372)."""

from __future__ import annotations

import copy
from typing import Any


def inject_into_system(messages: list[dict[str, Any]], enrichment: str) -> list[dict[str, Any]]:
    """Append enrichment to the system message (or prepend one). Pure (no mutation)."""
    if not enrichment:
        return messages
    out = copy.deepcopy(messages)
    for msg in out:
        if msg.get("role") == "system":
            existing = str(msg.get("content") or "")
            msg["content"] = f"{existing}\n\n{enrichment}" if existing else enrichment
            return out
    return [{"role": "system", "content": enrichment}, *out]
