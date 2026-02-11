"""Hybrid search pipeline -- vector + graph + LLM answer generation."""
from __future__ import annotations
import json
from typing import Dict, List, Optional

import structlog

from metatron.core.config import Settings
from metatron.llm import chat_completion  # TODO: async migration
from metatron.ingestion.processors.dates import (
    extract_date_from_text, extract_date_range, get_dates_in_range,
)
from metatron.observability.metrics import timed
from metatron.retrieval.prompts import (
    HYBRID_SYSTEM_PROMPT, TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT,
    TEAM_WORKFLOW_SCHEMA_SPEC,
)
from metatron.retrieval.routing import (
    _extract_json_object, is_jira_query, is_jira_result,
    should_use_team_workflow_schema,
)
from metatron.storage.qdrant import get_hybrid_store  # TODO: async migration
from metatron.storage.graph_ops import (  # TODO: async migration
    get_graph_entities, get_doc_labels_by_entities, get_related_documents,
    get_entities_by_doc_labels, get_graph_relationships,
)

logger = structlog.get_logger()
_s = Settings()
_MAX_TOTAL, _MAX_FRAG = _s.search_max_total_chars, _s.search_max_fragment_chars
_POOL_MUL, _POOL_MIN = _s.search_pool_multiplier, _s.search_pool_min
_DATE_MUL = int(getattr(_s, "search_date_multiplier", 3))
_JIRA_MUL = int(getattr(_s, "search_jira_multiplier", 2))
_GRAPH_DEPTH = int(getattr(_s, "search_graph_depth", 2))
_REL_DOCS = int(getattr(_s, "search_related_docs_limit", 5))
_CTX_EXTRA = int(getattr(_s, "search_context_extra", 5))

_TRANSLATE_SYS = "Translate the following query to English. Return ONLY the translation, nothing else."


@timed("translate_query")
def translate_query_to_english(query: str) -> str:  # TODO: async migration
    """Translate a Russian query to English for vector search."""
    if not any('\u0400' <= c <= '\u04FF' for c in query):
        return query
    try:
        t = chat_completion(
            messages=[{"role": "system", "content": _TRANSLATE_SYS},
                      {"role": "user", "content": query}],
            temperature=0.1, max_tokens=200, timeout=10,
        )
        return t.strip()
    except Exception:
        logger.warning("translate_query.failed", qlen=len(query))
    return query


def prioritize_results(results: list, query: str, k: int) -> list:
    """Confluence first, Jira second (reversed for Jira queries)."""
    jira = [m for m in results if is_jira_result(m)]
    docs = [m for m in results if not is_jira_result(m)]
    merged = (jira + docs) if is_jira_query(query) else (docs + jira)
    return merged[: max(k + _CTX_EXTRA, _POOL_MIN)]


def _doc_labels(results: List[Dict]) -> List[str]:
    out: List[str] = []
    for m in results:
        lb = m.get("doc_label") or (m.get("payload") or {}).get("doc_label")
        if lb:
            out.append(lb)
    return list(dict.fromkeys(out))


def _merge_unique(base: list, extra: list) -> list:
    seen = {hash((d.get("memory") or "")[:200]) for d in base if d.get("memory")}
    for r in extra:
        c = r.get("memory") or ""
        if c:
            h = hash(c[:200])
            if h not in seen:
                seen.add(h)
                base.append(r)
    return base


@timed("search")
def search_with_date_filter(  # TODO: async migration
    query: str, user_id: str = "user", k: int = 5,
    workspace_id: Optional[str] = None,
) -> list:
    """Hybrid search with date filtering (workspace-aware)."""
    store = get_hybrid_store(workspace_id)
    date_range = extract_date_range(query)
    if date_range:
        dates = get_dates_in_range(date_range[0], date_range[1])
        dd = store.search_by_date(dates, limit=k * _DATE_MUL)
        if dd:
            return _merge_unique(dd, store.hybrid_search(query, limit=k))[:k]
    td = extract_date_from_text(query)
    if td:
        dd = store.search_by_date([td], limit=k)
        if dd:
            if len(dd) < k:
                _merge_unique(dd, store.hybrid_search(query, limit=k))
            return dd[:k]
    if is_jira_query(query):
        jd = store.search_by_type("jira", limit=k * _JIRA_MUL)
        if jd:
            return _merge_unique(jd, store.hybrid_search(query, limit=k))[: k * _JIRA_MUL]
    return store.hybrid_search(query, limit=k)


def _collect_frags(base, seen, total):
    frags: List[str] = []
    for mem in base:
        text = mem.get("memory") or mem.get("data") or ""
        if len(text) > _MAX_FRAG:
            text = text[:_MAX_FRAG] + "..."
        th = hash(text[:200])
        if th in seen:
            continue
        if total + len(text) > _MAX_TOTAL:
            break
        frags.append(text); seen.add(th); total += len(text)
    return frags, seen, total


def _build_ctx(q, lang, frags, g_ents, g_rels, g_docs):
    jd = lambda o: json.dumps(o, ensure_ascii=False, indent=2)  # noqa: E731
    return (
        f"RESPOND IN {lang.upper()} ONLY.\n\nUser question:\n{q}\n\n"
        f"Vector search results (texts):\n{jd(frags)}\n\n"
        f"Graph entities:\n{jd(g_ents)}\n\n"
        f"Entity relationships:\n{jd(g_rels)}\n\n"
        f"Related documents:\n{jd(g_docs)}\n\n"
    )


@timed("hybrid_search_and_answer")
def hybrid_search_and_answer(  # noqa: C901  # TODO: async migration
    query: str, user_id: str = "user", k: int = 5,
    workspace_id: Optional[str] = None, intent_query: Optional[str] = None,
) -> str:
    """End-to-end hybrid search and answer generation."""
    rq = (intent_query or query or "").strip()
    use_schema = should_use_team_workflow_schema(rq)
    is_ru = any('\u0400' <= c <= '\u04FF' for c in rq)
    lang = "Russian" if is_ru else "English"
    sq = translate_query_to_english(query) if is_ru else query

    pool = max(k * _POOL_MUL, _POOL_MIN)
    raw = search_with_date_filter(sq, user_id=user_id, k=pool, workspace_id=workspace_id)
    base = prioritize_results(raw, query, k)
    frags, seen_h, total_c = _collect_frags(base, set(), 0)

    # -- Graph enrichment --
    dl = _doc_labels(base)
    g_ents = get_entities_by_doc_labels(dl, workspace_id) if dl else get_graph_entities(frags, workspace_id)
    names: set[str] = set()
    for e in g_ents:
        if e.get("name"):
            names.add(e["name"])
        for a in e.get("aliases", []) or []:
            names.add(a)
    g_rels: list = []
    g_docs: list = []
    if names:
        g_rels = get_graph_relationships(list(names), workspace_id, max_depth=_GRAPH_DEPTH)
        for r in g_rels:
            names.update(filter(None, [r.get("source"), r.get("target")]))
        g_docs = (get_doc_labels_by_entities(list(names), workspace_id)
                  if dl else get_related_documents(frags, workspace_id))
    # Expand context with graph-related documents
    if dl and g_docs:
        extra = [d["doc_label"] for d in g_docs if d.get("doc_label") and d["doc_label"] not in dl]
        if extra:
            for mem in get_hybrid_store(workspace_id).search_by_doc_labels(extra, limit=_REL_DOCS):
                text = mem.get("memory") or mem.get("data") or ""
                if len(text) > _MAX_FRAG:
                    text = text[:_MAX_FRAG] + "..."
                th = hash(text[:200])
                if th in seen_h or total_c + len(text) > _MAX_TOTAL:
                    continue
                frags.append(text); seen_h.add(th); total_c += len(text)

    ctx = _build_ctx(rq if use_schema else query, lang, frags, g_ents, g_rels, g_docs)
    if use_schema:
        c = chat_completion(
            messages=[{"role": "system", "content": TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT},
                      {"role": "user", "content": ctx + TEAM_WORKFLOW_SCHEMA_SPEC}],
            temperature=0.2, json_mode=True, timeout=60,
        )
        return (json.loads(_extract_json_object(c)).get("answer") or "").strip()
    ans = chat_completion(
        messages=[{"role": "system", "content": HYBRID_SYSTEM_PROMPT},
                  {"role": "user", "content": ctx + f"Provide a coherent answer in {lang}."}],
        temperature=0.2, timeout=60,
    )
    return ans.strip()
