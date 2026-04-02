"""Token-aware context budget management for LLM calls.

Estimates token counts without external tokenizer dependencies and
selects fragments that fit within a configurable token budget.
"""

from __future__ import annotations

import json

import structlog

logger = structlog.get_logger()

MAX_GRAPH_TOKENS: int = 2000
MIN_FRAGMENT_TOKENS: int = 2000


def estimate_tokens(text: str) -> int:
    """Estimate token count for mixed-language text.

    Rule of thumb: ~4 chars per token for Latin script,
    ~2 chars per token for Cyrillic/CJK. Fast and dependency-free.
    """
    if not text:
        return 0
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    other = len(text) - cyrillic
    return (other // 4) + (cyrillic // 2)


def estimate_graph_tokens(
    g_ents: list[dict],
    g_rels: list[dict],
    g_docs: list[dict],
) -> int:
    """Estimate tokens for the graph context section of the prompt."""
    raw = json.dumps(
        {"entities": g_ents, "relationships": g_rels, "documents": g_docs},
        ensure_ascii=False,
    )
    return estimate_tokens(raw)


def truncate_graph_context(
    g_ents: list[dict],
    g_rels: list[dict],
    g_docs: list[dict],
    max_tokens: int = MAX_GRAPH_TOKENS,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Truncate graph context to fit within max_tokens.

    Priority: Person entities first, then other entities, then
    relationships, then documents. Drops lowest-priority items first.
    """
    # Keep all Person entities, then fill with others
    person_ents = [e for e in g_ents if (e.get("type") or "").lower() == "person"]
    other_ents = [e for e in g_ents if (e.get("type") or "").lower() != "person"]

    # Start with persons, greedily add others
    kept_ents: list[dict] = list(person_ents)
    kept_rels: list[dict] = []
    kept_docs: list[dict] = []

    def _current() -> int:
        return estimate_graph_tokens(kept_ents, kept_rels, kept_docs)

    # Add other entities while budget allows
    for ent in other_ents:
        kept_ents.append(ent)
        if _current() > max_tokens:
            kept_ents.pop()
            break

    # Add relationships referencing kept entity names
    kept_names = {e.get("name") for e in kept_ents}
    for rel in g_rels:
        src = rel.get("source", "")
        tgt = rel.get("target", "")
        if src in kept_names or tgt in kept_names:
            kept_rels.append(rel)
            if _current() > max_tokens:
                kept_rels.pop()
                break

    # Add documents if room remains
    for doc in g_docs:
        kept_docs.append(doc)
        if _current() > max_tokens:
            kept_docs.pop()
            break

    original_tokens = estimate_graph_tokens(g_ents, g_rels, g_docs)
    final_tokens = _current()
    logger.warning(
        "token_budget.graph_truncated",
        original_tokens=original_tokens,
        truncated_to=final_tokens,
        ents_kept=len(kept_ents),
        ents_original=len(g_ents),
        rels_kept=len(kept_rels),
        rels_original=len(g_rels),
    )
    return kept_ents, kept_rels, kept_docs


def select_fragments_within_budget(
    fragments: list[str] | list[dict],
    max_tokens: int = 10000,
    system_prompt_tokens: int = 500,
    answer_reserve_tokens: int = 1500,
    graph_tokens: int = 0,
) -> list[str] | list[dict]:
    """Select as many fragments as fit within the token budget.

    Budget = max_tokens - system_prompt - answer_reserve - graph_context,
    but never less than MIN_FRAGMENT_TOKENS.
    Fragments are already ranked by relevance (best first).
    Greedily adds fragments until the budget is exhausted.

    Accepts both list[str] (legacy) and list[dict] (evidence packs)
    where dict has a "text" key.

    Args:
        fragments: Relevance-ranked fragments (str or dict with "text" key).
        max_tokens: Total token budget for the LLM context window.
        system_prompt_tokens: Estimated tokens for the system prompt.
        answer_reserve_tokens: Tokens reserved for LLM answer generation.
        graph_tokens: Tokens already allocated to graph context.

    Returns:
        List of fragments (same type as input) that fit within the budget.
    """
    computed = max_tokens - system_prompt_tokens - answer_reserve_tokens - graph_tokens
    available = max(computed, MIN_FRAGMENT_TOKENS)

    selected: list = []
    used = 0

    for frag in fragments:
        frag_text = frag["text"] if isinstance(frag, dict) else frag
        frag_tokens = estimate_tokens(frag_text)
        if used + frag_tokens > available:
            if not selected:
                ratio = available / max(frag_tokens, 1)
                if isinstance(frag, dict):
                    truncated = {**frag, "text": frag_text[: int(len(frag_text) * ratio)]}
                else:
                    truncated = frag_text[: int(len(frag_text) * ratio)]
                selected.append(truncated)
            break
        selected.append(frag)
        used += frag_tokens

    logger.info(
        "token_budget.selected",
        available=len(fragments),
        selected=len(selected),
        tokens_used=used,
        tokens_budget=available,
    )
    return selected
