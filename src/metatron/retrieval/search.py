"""Hybrid search pipeline -- vector + graph + LLM answer generation."""
from __future__ import annotations
import asyncio
import json
import re
from typing import Dict, List, Optional

import structlog

from metatron.core.config import Settings
from metatron.llm import chat_completion, chat_completion_with_retry  # TODO: async migration
from metatron.ingestion.processors.dates import (
    extract_date_from_text, extract_date_range,
)
from metatron.observability.metrics import timed
from metatron.retrieval.prompts import (
    HYBRID_SYSTEM_PROMPT, TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT,
    TEAM_WORKFLOW_SCHEMA_SPEC,
)
from metatron.retrieval.alias_registry import get_alias_registry
from metatron.retrieval.aliases import resolve_person_name
from metatron.retrieval.channels import (
    RecallContext, merge_channels,
    recall_dense, recall_exact, recall_metadata, recall_graph,
)
from metatron.retrieval.query_expansion import expand_query
from metatron.retrieval.token_budget import (
    MAX_GRAPH_TOKENS,
    estimate_graph_tokens, select_fragments_within_budget,
    truncate_graph_context,
)
from metatron.retrieval.routing import (
    _extract_json_object,
    should_use_team_workflow_schema,
)
from metatron.storage.qdrant import get_hybrid_store  # TODO: async migration
from metatron.storage.graph_ops import (  # TODO: async migration
    get_graph_entities, get_doc_labels_by_entities,
    get_entities_by_doc_labels, get_graph_relationships,
    get_relationships_at_date,
)

logger = structlog.get_logger()
_s = Settings()
_MAX_TOTAL, _MAX_FRAG = _s.search_max_total_chars, _s.search_max_fragment_chars
_GRAPH_DEPTH = int(getattr(_s, "search_graph_depth", 2))

_TRANSLATE_SYS = "Translate the following query to English. Return ONLY the translation, nothing else."


def _run_hooks_sync(plugin_manager, hook_name: str, context: dict) -> dict:
    """Run async pipeline hooks from synchronous code safely.

    Uses asyncio.run() which creates an isolated event loop — safe from
    thread pool threads where the main event loop is already running.

    IMPORTANT: hybrid_search_and_answer() must NOT be called directly from
    an async context (use asyncio.to_thread() or run_in_executor).
    When hybrid_search_and_answer is migrated to async, replace asyncio.run()
    with native await.
    """
    for hook in plugin_manager.get_pipeline_hooks(hook_name):
        try:
            context = asyncio.run(hook(context))
        except RuntimeError as e:
            if "cannot be called from a running event loop" in str(e):
                structlog.get_logger().error(
                    "hooks.async_conflict", hook=hook_name, error=str(e),
                )
            else:
                raise
    return context




_ACTIVITY_KW = [
    "doing", "working", "active", "progress",
    "делает", "работает", "занимается", "текущ",
]

_JIRA_KEY_RE = re.compile(r'\b([A-Z]{2,}-\d+)\b', re.IGNORECASE)

_PERSON_RU = re.compile(
    r'(?:делает|занимается|работает|насчёт|насчет|про)\s+(\w+)',
    re.IGNORECASE,
)
_PERSON_EN = re.compile(
    r'what\s+is\s+(\w+)\s+doing'
    r'|what\s+(\w+)\s+is\s+working'
    r'|(?:what|how|tell\s+\w*)\s+about\s+(\w+)',
    re.IGNORECASE,
)

_PROPER_NOUN_RE = re.compile(
    r'(?:[A-ZА-ЯЁ][a-zа-яё]+(?:\s+[A-ZА-ЯЁ][a-zа-яё]+)+)',
)

# Matches uppercase tokens like "3M", "AMD", "AES", "COCACOLA", "IBM"
# and multi-word company names like "Activision Blizzard", "Best Buy"
_COMPANY_TOKEN_RE = re.compile(r'\b([A-Z0-9]{2,})\b')
_COMPANY_MULTI_RE = re.compile(
    r'\b((?:[A-Z][a-z]+\s+){1,3}[A-Z][a-z]+)\b',
)


def extract_proper_nouns(query: str) -> list[str]:
    """Extract multi-word capitalized phrases (proper nouns) from query.

    "What is Project Aurora?" → ["Project Aurora"]
    "What did Marina Volkov do?" → ["Marina Volkov"]
    """
    return _PROPER_NOUN_RE.findall(query)


def extract_title_entities(query: str) -> list[str]:
    """Extract entity names that may appear in document titles.

    Handles:
    - Short uppercase tokens: "3M", "AMD", "AES", "IBM"
    - Multi-word names: "Activision Blizzard", "Best Buy", "American Express"
    - Proper nouns: "Marina Volkov"

    Filters out common English words (FY, USD, Q2, etc.).
    """
    stop = {
        "FY", "USD", "FY2017", "FY2018", "FY2019", "FY2020", "FY2021",
        "FY2022", "FY2023", "FY2024", "YOY", "PP", "Q1", "Q2", "Q3", "Q4",
        "CEO", "CFO", "CTO", "SEC", "US", "UK", "EU", "IT", "AI", "ML",
        "OR", "IF", "IS", "AS", "AT", "BY", "TO", "OF", "IN", "ON", "AN",
        "AND", "THE", "FOR", "NOT", "GDP", "IPO", "ROE", "ROA", "PE",
        "GAAP", "NON", "EBITDA", "CAPEX", "OPEX",
    }
    entities: list[str] = []

    # Multi-word names first (higher priority)
    for m in _COMPANY_MULTI_RE.finditer(query):
        name = m.group(1)
        if len(name) > 3:
            entities.append(name)

    # Short uppercase tokens
    for m in _COMPANY_TOKEN_RE.finditer(query):
        token = m.group(1)
        if token not in stop and not token.isdigit():
            entities.append(token)

    # Proper nouns (Cyrillic too)
    entities.extend(extract_proper_nouns(query))

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for e in entities:
        key = e.upper()
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result



def _boost_title_matches(query: str, results: list[dict],
                         entities: list[str] | None = None) -> list[dict]:
    """Boost results whose title contains an entity from the query."""
    if entities is None:
        entities = extract_title_entities(query)
    if not entities:
        return results

    entities_lower = [e.lower() for e in entities]

    boosted: list[dict] = []
    rest: list[dict] = []
    for r in results:
        title = (r.get("title") or (r.get("payload") or {}).get("title") or "").lower()
        if any(e in title for e in entities_lower):
            boosted.append(r)
        else:
            rest.append(r)

    if boosted:
        logger.info("search.title_boost", entities=entities, boosted=len(boosted))
    return boosted + rest


def _search_by_title(query: str, workspace_id: Optional[str], limit: int = 5) -> list[dict]:
    """Search for documents where title matches entities in query."""
    entities = extract_title_entities(query)
    if not entities:
        return []
    try:
        store = get_hybrid_store(workspace_id)
        results: list[dict] = []
        for entity in entities:
            for variant in _title_variants(entity):
                matches = store.scroll_by_title(variant, limit=limit)
                results = _merge_unique(results, matches)
        if results:
            logger.info("search.title_injection", entities=entities, count=len(results))
        return results
    except Exception as e:
        logger.warning("search.title_injection_failed", error=str(e))
        return []


def _title_variants(entity: str) -> list[str]:
    """Generate case/spacing variants for title matching."""
    variants = [entity, entity.upper(), entity.lower()]
    collapsed = entity.replace(" ", "")
    if collapsed != entity:
        variants.extend([collapsed, collapsed.upper(), collapsed.lower()])
    return list(dict.fromkeys(variants))  # dedup, preserve order


def _inject_jira_key_results(query: str, workspace_id: Optional[str]) -> list[dict]:
    """Extract Jira keys from query and fetch exact matches via doc_label."""
    keys = _JIRA_KEY_RE.findall(query)
    if not keys:
        return []
    keys = list(dict.fromkeys(k.upper() for k in keys))  # dedup, preserve order
    try:
        store = get_hybrid_store(workspace_id)
        results = store.search_by_doc_labels(keys)
        if results:
            logger.info("search.jira_key_injection", keys=keys, count=len(results))
        return results
    except Exception as e:
        logger.warning("search.jira_key_injection_failed", error=str(e))
        return []


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



def _collect_frags(
    base: list[dict], seen: set[int], total: int,
) -> tuple[list[str], set[int], int, dict[str, dict]]:
    frags: List[str] = []
    doc_stats: Dict[str, Dict] = {}  # {doc_label: {title, word_count, fetch_count}}
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

        # Track per-document stats for FinOps cost savings
        dl = mem.get("doc_label") or (mem.get("payload") or {}).get("doc_label") or ""
        if dl:
            words = len(text.split())
            if dl not in doc_stats:
                doc_stats[dl] = {"title": title, "word_count": 0, "fetch_count": 0}
            doc_stats[dl]["word_count"] += words
            doc_stats[dl]["fetch_count"] += 1
            if title:
                doc_stats[dl]["title"] = title
    return frags, seen, total, doc_stats


_SOURCE_ICONS = {"confluence": "\U0001f4c4", "jira": "\U0001f4cb", "upload": "\U0001f4ce", "notion": "\U0001f4d3"}


def _append_sources(answer: str, results: list) -> str:
    """Append a sources section to the answer with document titles and types.

    All unique sources are included so that every ``[$[title]$]`` reference
    marker in the LLM answer can be resolved to a URL by downstream consumers
    (frontend / OpenAI-compat layer).
    """
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
        url = (
            mem.get("url")
            or (mem.get("payload") or {}).get("url")
            or ""
        )
        if url:
            sources.append(f"{icon} {title} \u2014 {url}")
        else:
            sources.append(f"{icon} {title}")
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


def _build_recall_context(
    original_query: str,
    translated_query: str,
    expanded_query: str,
    detected_language: str,
    workspace_id: str | None,
    access_filter=None,
    settings: Settings | None = None,
) -> RecallContext:
    """Consolidate all extraction logic into a single RecallContext.

    Extracts Jira keys, title entities, person names, date ranges,
    and activity signals from the query text. This replaces the scattered
    inline extraction that was previously spread across lines 616-668
    of hybrid_search_and_answer.
    """
    # Jira key extraction
    jira_keys = _JIRA_KEY_RE.findall(original_query)
    jira_keys = list(dict.fromkeys(k.upper() for k in jira_keys))

    # Title entity extraction
    title_entities = extract_title_entities(original_query)

    # Date extraction
    date_range = extract_date_range(original_query)
    extracted_dates: tuple | None = None
    if date_range:
        from metatron.ingestion.processors.dates import get_dates_in_range
        dates_list = get_dates_in_range(date_range[0], date_range[1])
        if dates_list:
            extracted_dates = tuple(dates_list)
    if not extracted_dates:
        single_date = extract_date_from_text(original_query)
        if single_date:
            extracted_dates = (single_date,)

    # Activity detection
    rq_lower = original_query.lower()
    is_activity = any(kw in rq_lower for kw in _ACTIVITY_KW)

    # Person detection
    detected_person: list[str] = []
    m = _PERSON_RU.search(rq_lower) or _PERSON_EN.search(original_query)
    if m:
        person_token = next((g for g in m.groups() if g), None)
        if person_token:
            person_token = person_token.strip()
            full_names = get_alias_registry().resolve(person_token)
            if not full_names:
                full_names = resolve_person_name(person_token)
            detected_person = list(full_names) if full_names else []

    return RecallContext(
        original_query=original_query,
        translated_query=translated_query,
        expanded_query=expanded_query,
        detected_language=detected_language,
        workspace_id=workspace_id,
        access_filter=access_filter,
        settings=settings or _s,
        extracted_jira_keys=jira_keys,
        extracted_title_entities=title_entities,
        extracted_dates=extracted_dates,
        detected_person=detected_person,
        is_activity_query=is_activity,
    )


@timed("hybrid_search_and_answer")
def hybrid_search_and_answer(  # noqa: C901  # TODO: async migration
    query: str, user_id: str = "user", k: int = 25,
    workspace_id: Optional[str] = None, intent_query: Optional[str] = None,
    return_trace: bool = False,
    plugin_manager=None,
) -> str | dict:
    """End-to-end hybrid search and answer generation."""
    import time
    start_time = time.time()
    
    rq = (intent_query or query or "").strip()
    use_schema = should_use_team_workflow_schema(rq)
    lang = detect_response_language(rq)

    # Expand query for better BM25 recall (adds status keywords, synonyms)
    eq = expand_query(rq)
    # Translate expanded query for vector/BM25 search if it has Cyrillic
    sq = translate_query_to_english(eq) if _has_cyrillic(eq) else eq

    # -- ACL pre-filter: restrict search to user's groups --
    access_filter = None
    if plugin_manager:
        hook_ctx = _run_hooks_sync(plugin_manager, "search_pre_filter", {
            "user_id": user_id, "workspace_id": workspace_id, "query": rq,
        })
        access_filter = hook_ctx.get("access_filter")

    # Store user_groups from pre-filter hook for graph enrichment
    user_groups = None
    if plugin_manager and access_filter:
        user_groups = hook_ctx.get("user_groups")

    # -- Build recall context (consolidates all extraction logic) --
    recall_ctx = _build_recall_context(
        original_query=rq,
        translated_query=sq,
        expanded_query=eq,
        detected_language=lang,
        workspace_id=workspace_id,
        access_filter=access_filter,
        settings=_s,
    )

    # -- Entity extraction for title boost (still needed downstream) --
    entities = recall_ctx.extracted_title_entities

    # -- Run 4 recall channels --
    dense_results = recall_dense(recall_ctx)
    exact_results = recall_exact(recall_ctx)
    metadata_results = recall_metadata(recall_ctx)
    graph_results = recall_graph(recall_ctx)

    # -- Merge and deduplicate across channels --
    merged = merge_channels([dense_results, exact_results, metadata_results, graph_results])

    # Convert ScoredResult back to legacy dict format for downstream compatibility
    raw = [sr["memory"] for sr in merged]

    base = diversify_results(raw, k=max(k * 2, 10))
    _post_diversify_count = len(base)
    base = _boost_title_matches(rq, base, entities=entities)

    _pre_rerank_count = len(base)
    if _s.reranker_enabled:
        from metatron.retrieval.reranker import rerank
        base = rerank(query=rq, results=base, top_k=k)
    _post_rerank_count = len(base)

    # -- ACL post-rerank: defense-in-depth filter --
    if plugin_manager:
        ctx = _run_hooks_sync(plugin_manager, "search_post_rerank", {
            "chunks": base, "user_id": user_id, "workspace_id": workspace_id,
        })
        base = ctx.get("chunks", base)

    frags, seen_h, total_c, doc_stats = _collect_frags(base, set(), 0)

    # -- Graph enrichment (graceful degradation: continue without graph if unavailable) --
    g_ents: list = []
    g_rels: list = []
    g_docs: list = []
    try:
        dl = _doc_labels(base)
        g_ents = get_entities_by_doc_labels(dl, workspace_id) if dl else get_graph_entities(frags, workspace_id)
        names: set[str] = set()
        for e in g_ents:
            if e.get("name"):
                names.add(e["name"])
            for a in e.get("aliases", []) or []:
                names.add(a)
        if names:
            date_range = extract_date_range(rq)
            if date_range:
                g_rels = get_relationships_at_date(
                    list(names), target_date=date_range[0],
                    workspace_id=workspace_id, max_depth=_GRAPH_DEPTH)
            else:
                g_rels = get_graph_relationships(
                    list(names), workspace_id,
                    max_depth=_GRAPH_DEPTH, active_only=True)
            for r in g_rels:
                names.update(filter(None, [r.get("source"), r.get("target")]))
            g_docs = (get_doc_labels_by_entities(list(names), workspace_id,
                                                user_groups=user_groups) if dl else [])
        # Graph docs kept as metadata only — document chunks come from recall channels
    except Exception:
        logger.warning("search.graph_enrichment_failed", exc_info=True)

    # -- Token budget: cap graph context, then select fragments --
    g_tokens = estimate_graph_tokens(g_ents, g_rels, g_docs)
    if g_tokens > MAX_GRAPH_TOKENS:
        g_ents, g_rels, g_docs = truncate_graph_context(
            g_ents, g_rels, g_docs, MAX_GRAPH_TOKENS,
        )
        g_tokens = estimate_graph_tokens(g_ents, g_rels, g_docs)
    frags = select_fragments_within_budget(
        frags,
        max_tokens=_s.llm_context_max_tokens,
        answer_reserve_tokens=_s.llm_answer_reserve_tokens,
        graph_tokens=g_tokens,
    )

    # use_schema mode: use only current question (rq) to avoid history noise in structured output
    # regular mode: use full composite query to leverage conversation context for follow-ups
    ctx = _build_ctx(rq if use_schema else query, lang, frags, g_ents, g_rels, g_docs)
    try:
        if use_schema:
            sys_prompt = TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT.format(response_language=lang)
            c = chat_completion_with_retry(
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": ctx + TEAM_WORKFLOW_SCHEMA_SPEC}],
                temperature=0.2, json_mode=True, timeout=60,
            )
            answer = (json.loads(_extract_json_object(c)).get("answer") or "").strip()
        else:
            sys_prompt = HYBRID_SYSTEM_PROMPT.format(response_language=lang)
            answer = chat_completion_with_retry(
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": ctx}],
                temperature=0.2, timeout=60,
            ).strip()
    except Exception:
        logger.error("search.llm_answer_failed", exc_info=True)
        n = len(base)
        return f"Found {n} relevant documents but couldn't generate an answer. Please try again."

    # Return full trace for benchmarker integration when requested
    if return_trace:
        _token_budget_used = sum(len(f) for f in frags) // 4 if frags else 0
        result = {
            "answer": _append_sources(answer, base),
            "source_results": base,
            "fragments": frags,
            "graph_entities": g_ents,
            "graph_relations": g_rels,
            "graph_docs": g_docs,
            "pipeline_stages": {
                "original_query": rq,
                "translated_query": sq,
                "expanded_query": eq,
                "detected_language": lang,
                "recall_dense_count": len(dense_results),
                "recall_exact_count": len(exact_results),
                "recall_metadata_count": len(metadata_results),
                "recall_graph_count": len(graph_results),
                "recall_total_unique": len(merged),
                "pre_rerank_count": _pre_rerank_count,
                "post_rerank_count": _post_rerank_count,
                "post_diversify_count": _post_diversify_count,
                "fragment_count": len(frags),
                "token_budget_used": _token_budget_used,
            },
            "retrieved_doc_labels": [
                r.get("doc_label", "") for r in base if r.get("doc_label")
            ],
        }
    else:
        result = _append_sources(answer, base)
    
    # Log query trace to PostgreSQL (async, non-blocking)
    if workspace_id:
        try:
            total_ms = (time.time() - start_time) * 1000
            # Count total words in source fragments sent to LLM context.
            # Used by FinOps time-savings calculation: manual_reading_time = (words / 150 WPM) * 1.5
            source_word_count = sum(len(frag.split()) for frag in frags) if frags else 0
            trace_data = {
                "query": rq,
                "user_id": user_id,
                "k": k,
                "num_results": len(base),
                "num_fragments": len(frags),
                "num_entities": len(g_ents),
                "num_relations": len(g_rels),
                "use_schema": use_schema,
                "language": lang,
                "source_word_count": source_word_count,
                "recall_dense_count": len(dense_results),
                "recall_exact_count": len(exact_results),
                "recall_metadata_count": len(metadata_results),
                "recall_graph_count": len(graph_results),
                "recall_total_unique": len(merged),
            }
            
            from metatron.storage.pg_connection import store_query_trace_sync
            store_query_trace_sync(workspace_id, rq, trace_data, total_ms)

            # Track per-document fetch stats for FinOps cost savings
            if doc_stats:
                from metatron.storage.pg_connection import upsert_document_fetch_stats_sync
                upsert_document_fetch_stats_sync(workspace_id, doc_stats)
        except Exception as e:
            logger.warning("search.trace_logging_failed", error=str(e))
    
    return result
