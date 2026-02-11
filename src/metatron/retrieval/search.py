"""Hybrid search pipeline -- vector + graph + LLM answer generation."""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
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
from metatron.retrieval.aliases import resolve_person_name
from metatron.retrieval.query_expansion import expand_query
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

_ACTIVITY_KW = [
    "doing", "working", "active", "progress",
    "делает", "работает", "занимается", "текущ",
]

_PERSON_RU = re.compile(r'(?:делает|занимается|работает)\s+(\w+)', re.IGNORECASE)
_PERSON_EN = re.compile(r'what\s+is\s+(\w+)\s+doing|what\s+(\w+)\s+is\s+working', re.IGNORECASE)


def detect_response_language(query: str) -> str:
    """Detect primary language of the query.

    Uses ratio of Cyrillic to total letter characters. If Cyrillic makes up
    >=30% of letters, the query is Russian — this handles mixed queries like
    "Что такое Metatron?" (Russian question with an English proper noun)
    and "Расскажи про analytics dashboard" (Russian with English terms).

    Pure-English queries like "What about задача MTRNIX-123?" where a single
    Russian word appears in an otherwise English sentence stay English because
    the Cyrillic ratio is low.
    """
    cyrillic = sum(1 for c in query if '\u0400' <= c <= '\u04FF')
    latin = sum(1 for c in query if 'a' <= c.lower() <= 'z')
    total = cyrillic + latin
    if total == 0:
        return "English"
    if cyrillic / total >= 0.3:
        return "Russian"
    return "English"


def _has_cyrillic(text: str) -> bool:
    """Return True if text contains any Cyrillic characters."""
    return any('\u0400' <= c <= '\u04FF' for c in text)


@timed("translate_query")
def translate_query_to_english(query: str) -> str:  # TODO: async migration
    """Translate a Russian query to English for vector search."""
    if not _has_cyrillic(query):
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



def _result_type(r: dict) -> str:
    """Extract source type from a search result dict."""
    return (
        r.get("type")
        or (r.get("payload") or {}).get("type")
        or (r.get("metadata") or {}).get("type")
        or "unknown"
    ).lower()


_MIN_PER_SOURCE = 2


def diversify_results(results: list, k: int = 10) -> list:
    """Ensure source diversity in search results.

    Instead of letting one source dominate, guarantees minimum
    representation from each source type that has results.

    Strategy:
    - Reserve min(2, available) slots per source type
    - Fill remaining slots by relevance score
    """
    if not results or k <= 0:
        return results[:k]

    by_source: dict[str, list[dict]] = {}
    for r in results:
        by_source.setdefault(_result_type(r), []).append(r)

    if len(by_source) <= 1:
        return results[:k]

    selected: list[dict] = []
    remaining: list[dict] = []

    for items in by_source.values():
        take = min(_MIN_PER_SOURCE, len(items))
        selected.extend(items[:take])
        remaining.extend(items[take:])

    slots_left = k - len(selected)
    if slots_left > 0 and remaining:
        remaining.sort(key=lambda r: r.get("score", 0) or 0, reverse=True)
        selected.extend(remaining[:slots_left])

    return selected[:k]


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
    date_query: Optional[str] = None,
) -> list:
    """Hybrid search with date filtering (workspace-aware).

    Args:
        query: Search query (may be expanded/translated for BM25+vector).
        date_query: Original query for date extraction (if different from query).
    """
    store = get_hybrid_store(workspace_id)
    date_range = extract_date_range(date_query or query)
    if date_range:
        dates = get_dates_in_range(date_range[0], date_range[1])
        logger.info("search.date_filter", start=date_range[0], end=date_range[1],
                     num_dates=len(dates))
        dd = store.search_by_date(dates, limit=k * _DATE_MUL)
        # Always widen by ±7 days so nearby activity (e.g. Jira updated
        # a few days before "this week") is included alongside exact matches.
        start = datetime.strptime(date_range[0], "%Y-%m-%d")
        end = datetime.strptime(date_range[1], "%Y-%m-%d")
        wider_start = (start - timedelta(days=7)).strftime("%Y-%m-%d")
        wider_end = (end + timedelta(days=7)).strftime("%Y-%m-%d")
        wider_dates = get_dates_in_range(wider_start, wider_end)
        wider = store.search_by_date(wider_dates, limit=k * _DATE_MUL)
        if dd or wider:
            merged = _merge_unique(dd or [], wider or [])
            merged = _merge_unique(merged, store.hybrid_search(query, limit=k))
            if wider and not dd:
                logger.info("search.date_widened", original=date_range,
                            wider=(wider_start, wider_end), results=len(wider))
            return diversify_results(merged, k=k)
        logger.warning("search.date_filter.empty", start=date_range[0], end=date_range[1])
    td = extract_date_from_text(date_query or query)
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

        # Prefix with source label so the LLM knows the origin
        source_type = _result_type(mem)
        title = (mem.get("title")
                 or (mem.get("payload") or {}).get("title")
                 or "")
        if source_type != "unknown" or title:
            parts = []
            if source_type != "unknown":
                parts.append(f"[{source_type.upper()}]")
            if title:
                parts.append(title)
            text = " ".join(parts) + "\n" + text

        th = hash(text[:200])
        if th in seen:
            continue
        if total + len(text) > _MAX_TOTAL:
            break
        frags.append(text); seen.add(th); total += len(text)
    return frags, seen, total


_SOURCE_ICONS = {"confluence": "\U0001f4c4", "jira": "\U0001f4cb"}
_MAX_SOURCES = 5


def _append_sources(answer: str, results: list) -> str:
    """Append a sources section to the answer with document titles and types."""
    seen_titles: set[str] = set()
    sources: list[str] = []
    for mem in results:
        title = (
            mem.get("title")
            or (mem.get("payload") or {}).get("title")
            or ""
        )
        source_type = _result_type(mem)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        icon = _SOURCE_ICONS.get(source_type, "\U0001f4c4")
        sources.append(f"{icon} {title}")
        if len(sources) >= _MAX_SOURCES:
            break
    if sources:
        return answer + "\n\n\U0001f4da Sources:\n" + "\n".join(sources)
    return answer


def _build_ctx(q, lang, frags, g_ents, g_rels, g_docs):
    jd = lambda o: json.dumps(o, ensure_ascii=False, indent=2)  # noqa: E731
    return (
        f"⚠️ RESPOND ONLY IN {lang.upper()}. Translate all information to {lang} if needed.\n\n"
        f"User question:\n{q}\n\n"
        f"Vector search results (texts):\n{jd(frags)}\n\n"
        f"Graph entities:\n{jd(g_ents)}\n\n"
        f"Entity relationships:\n{jd(g_rels)}\n\n"
        f"Related documents:\n{jd(g_docs)}\n\n"
        f"Provide a coherent answer. LANGUAGE: {lang.upper()} ONLY."
    )


@timed("hybrid_search_and_answer")
def hybrid_search_and_answer(  # noqa: C901  # TODO: async migration
    query: str, user_id: str = "user", k: int = 5,
    workspace_id: Optional[str] = None, intent_query: Optional[str] = None,
) -> str:
    """End-to-end hybrid search and answer generation."""
    rq = (intent_query or query or "").strip()
    use_schema = should_use_team_workflow_schema(rq)
    lang = detect_response_language(rq)

    # Expand query for better BM25 recall (adds status keywords, synonyms)
    eq = expand_query(rq)
    # Translate expanded query for vector/BM25 search if it has Cyrillic
    sq = translate_query_to_english(eq) if _has_cyrillic(eq) else eq

    # -- Inject status/person-filtered results for activity queries --
    # Person-specific takes priority: "Что делает Женя?" injects only
    # Evgeny's tasks, NOT all In Progress tasks from the whole team.
    injected: list = []
    rq_lower = rq.lower()
    is_activity = any(kw in rq_lower for kw in _ACTIVITY_KW)

    # Detect person first
    person = None
    m = _PERSON_RU.search(rq_lower) or _PERSON_EN.search(rq)
    if m:
        person = (m.group(1) or (m.group(2) if m.lastindex and m.lastindex >= 2 else None))

    if person:
        # Person-specific: only their tasks, skip general In Progress
        person = person.strip()
        full_names = resolve_person_name(person)
        try:
            store = get_hybrid_store(workspace_id)
            for fname in full_names:
                person_tasks = store.search_by_assignee(fname, limit=10)
                if person_tasks:
                    logger.info("search.injected_person_tasks",
                                person=person, resolved=fname, count=len(person_tasks))
                    injected = _merge_unique(injected, person_tasks)
        except Exception as e:
            logger.warning("search.person_injection_failed", error=str(e))
    elif is_activity:
        # General activity (no specific person): all In Progress tasks
        try:
            store = get_hybrid_store(workspace_id)
            for status in ("In Progress", "В работе", "Selected for Development"):
                batch = store.search_by_status(status, limit=10)
                if batch:
                    injected = _merge_unique(injected, batch)
            if injected:
                logger.info("search.injected_in_progress", count=len(injected))
        except Exception as e:
            logger.warning("search.in_progress_injection_failed", error=str(e))

    pool = max(k * _POOL_MUL, _POOL_MIN)
    raw = search_with_date_filter(
        sq, user_id=user_id, k=pool, workspace_id=workspace_id,
        date_query=rq,  # original query for date extraction (not expanded)
    )
    if injected:
        raw = _merge_unique(injected, raw)
    base = diversify_results(raw, k=max(k * 2, 10))
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

    # use_schema mode: use only current question (rq) to avoid history noise in structured output
    # regular mode: use full composite query to leverage conversation context for follow-ups
    ctx = _build_ctx(rq if use_schema else query, lang, frags, g_ents, g_rels, g_docs)
    if use_schema:
        sys_prompt = TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT.format(response_language=lang)
        c = chat_completion(
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": ctx + TEAM_WORKFLOW_SCHEMA_SPEC}],
            temperature=0.2, json_mode=True, timeout=60,
        )
        answer = (json.loads(_extract_json_object(c)).get("answer") or "").strip()
    else:
        sys_prompt = HYBRID_SYSTEM_PROMPT.format(response_language=lang)
        answer = chat_completion(
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": ctx}],
            temperature=0.2, timeout=60,
        ).strip()

    return _append_sources(answer, base)
