"""Hybrid search pipeline -- vector + graph + LLM answer generation."""
from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import structlog

from metatron.core.config import Settings
from metatron.ingestion.processors.dates import (
    extract_date_from_text,
    extract_date_range,
)
from metatron.llm import chat_completion, chat_completion_with_retry  # TODO: async migration
from metatron.observability.metrics import timed
from metatron.retrieval.alias_registry import get_alias_registry
from metatron.retrieval.aliases import resolve_person_name
from metatron.retrieval.channels import (
    RecallContext,
    merge_channels,
    recall_dense,
    recall_exact,
    recall_graph,
    recall_metadata,
)
from metatron.retrieval.prompts import (
    HYBRID_SYSTEM_PROMPT,
    QUERY_RESOLVER_SYSTEM_PROMPT,
    TEAM_WORKFLOW_SCHEMA_SPEC,
    TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT,
)
from metatron.retrieval.query_classifier import classify_query, get_profile_weights
from metatron.retrieval.query_expansion import expand_query
from metatron.retrieval.routing import (
    _extract_json_object,
    should_use_team_workflow_schema,
)
from metatron.retrieval.scoring import (
    compute_final_score,
    compute_signal_score,
    normalize_rerank_scores,
    recency_score,
    source_balance,
)
from metatron.retrieval.token_budget import (
    MAX_GRAPH_TOKENS,
    estimate_graph_tokens,
    select_fragments_within_budget,
    truncate_graph_context,
)
from metatron.storage.graph_ops import (  # TODO: async migration
    get_doc_labels_by_entities,
    get_entities_by_doc_labels,
    get_graph_entities,
    get_graph_relationships,
    get_relationships_at_date,
)

logger = structlog.get_logger()
_s = Settings()
_MAX_TOTAL, _MAX_FRAG = _s.search_max_total_chars, _s.search_max_fragment_chars
_GRAPH_DEPTH = int(getattr(_s, "search_graph_depth", 2))

_TRANSLATE_SYS = "Translate the following query to English. Return ONLY the translation, nothing else."

_recall_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="recall")


@timed("resolve_query")
def resolve_query(query: str) -> str:
    """Rewrite context-dependent references in the query to concrete values.

    Uses LLM to resolve relative dates ("the day before that" → "March 11"),
    pronouns ("tell me about it" → "tell me about Project Aurora"), and other
    references that depend on conversation context.

    Falls back to original query on any error.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        user_msg = f"Current date: {today}\n\nQuery: {query}"
        resolved = chat_completion(
            messages=[
                {"role": "system", "content": QUERY_RESOLVER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=200,
            timeout=10,
        )
        resolved = resolved.strip()

        if not resolved or len(resolved) < 3 or len(resolved) > len(query) * 3:
            logger.warning(
                "query.resolve_fallback",
                reason="invalid_response",
                original=query[:100],
                response_len=len(resolved) if resolved else 0,
            )
            return query

        if resolved != query:
            logger.info(
                "query.resolved",
                original=query[:100],
                resolved=resolved[:200],
            )
        return resolved
    except Exception as e:
        logger.warning("query.resolve_failed", error=str(e))
        return query


def _run_recall_channels(ctx: RecallContext) -> tuple[list, list, list, list]:
    """Run 4 recall channels in parallel using thread pool.

    Each channel is sync (Qdrant/Memgraph clients are sync), so we use
    threads for true parallelism. Returns (dense, exact, metadata, graph).
    """
    futures = [
        _recall_executor.submit(recall_dense, ctx),
        _recall_executor.submit(recall_exact, ctx),
        _recall_executor.submit(recall_metadata, ctx),
        _recall_executor.submit(recall_graph, ctx),
    ]
    return tuple(f.result() for f in futures)


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



def _doc_labels(results: list[dict]) -> list[str]:
    out: list[str] = []
    for m in results:
        lb = m.get("doc_label") or (m.get("payload") or {}).get("doc_label")
        if lb:
            out.append(lb)
    return list(dict.fromkeys(out))



def _collect_frags(
    base: list[dict], seen: set[int], total: int,
) -> tuple[list[dict], set[int], int, dict[str, dict]]:
    frags: list[dict] = []
    doc_stats: dict[str, dict] = {}  # {doc_label: {title, word_count, fetch_count}}
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
        seen.add(th); total += len(text)

        source_role = (mem.get("source_role")
                       or (mem.get("payload") or {}).get("source_role")
                       or "knowledge_base")
        date = (mem.get("date")
                or (mem.get("payload") or {}).get("date")
                or "")
        dl = mem.get("doc_label") or (mem.get("payload") or {}).get("doc_label") or ""

        frags.append({
            "text": text,
            "source_type": source_type,
            "source_role": source_role,
            "title": title,
            "date": date,
            "doc_label": dl,
            "evidence_marker": "",  # set later by _mark_evidence_role
        })

        # Track per-document stats for FinOps cost savings
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

# Maps query classifier profile → which source_role gets PRIMARY evidence marker.
# None means all fragments get SUPPORTING (zero behavior change for mixed/unknown).
PROFILE_PRIMARY_ROLE: dict[str, str | None] = {
    "execution":     "task_tracker",
    "documentation": "knowledge_base",
    "user_file":     "user_upload",
    "relationship":  "knowledge_base",
    "temporal":      "task_tracker",
    "mixed":         None,
}


def _mark_evidence_role(frags: list[dict], query_profile: str) -> None:
    """Label each fragment as PRIMARY or SUPPORTING based on query profile.

    Mutates frags in place. PRIMARY = source_role matches the expected
    primary source for this query profile. Everything else is SUPPORTING.
    """
    primary_role = PROFILE_PRIMARY_ROLE.get(query_profile)
    for frag in frags:
        if primary_role and frag["source_role"] == primary_role:
            frag["evidence_marker"] = "PRIMARY"
        else:
            frag["evidence_marker"] = "SUPPORTING"


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


# Fixed display order for source_role groups (when no PRIMARY group takes priority)
_SOURCE_ROLE_ORDER = ["knowledge_base", "task_tracker", "user_upload", "communication"]
_SOURCE_ROLE_LABELS = {
    "knowledge_base": "Knowledge base sources",
    "task_tracker": "Task tracker sources",
    "user_upload": "User upload sources",
    "communication": "Communication sources",
}


def _build_ctx(q, lang, frags, g_ents, g_rels, g_docs):
    jd = lambda o: json.dumps(o, ensure_ascii=False, indent=2)  # noqa: E731

    # -- Group fragments by source_role --
    groups: dict[str, list[dict]] = {}
    primary_group: str | None = None
    for f in frags:
        role = f.get("source_role", "knowledge_base")
        groups.setdefault(role, []).append(f)
        if f.get("evidence_marker") == "PRIMARY" and primary_group is None:
            primary_group = role

    # Build ordered list: primary group first, then fixed order
    ordered_roles: list[str] = []
    if primary_group:
        ordered_roles.append(primary_group)
    for role in _SOURCE_ROLE_ORDER:
        if role != primary_group and role in groups:
            ordered_roles.append(role)
    # Any unknown roles appended at end
    for role in groups:
        if role not in ordered_roles:
            ordered_roles.append(role)

    # -- Assemble fragment sections --
    frag_sections: list[str] = []
    for role in ordered_roles:
        label = _SOURCE_ROLE_LABELS.get(role, f"{role} sources")
        lines = [f"## {label}"]
        for f in groups[role]:
            marker = f.get("evidence_marker", "SUPPORTING")
            date_suffix = f" ({f['date']})" if f.get("date") else ""
            # Text already has [TYPE] Title\ncontent prefix from _collect_frags
            # Replace the first line with marker-prefixed version
            text_lines = f["text"].split("\n", 1)
            header = text_lines[0]
            body = text_lines[1] if len(text_lines) > 1 else ""
            lines.append(f"[{marker}] {header}{date_suffix}")
            if body:
                lines.append(body)
            lines.append("")  # blank line between fragments
        frag_sections.append("\n".join(lines))

    fragment_text = "\n".join(frag_sections)

    # -- Graph context (unchanged format) --
    graph_parts: list[str] = []
    if g_ents or g_rels or g_docs:
        graph_parts.append("## Graph context")
        if g_ents:
            graph_parts.append(f"Entities: {jd(g_ents)}")
        if g_rels:
            graph_parts.append(f"Relationships: {jd(g_rels)}")
        if g_docs:
            graph_parts.append(f"Related documents: {jd(g_docs)}")
    graph_text = "\n".join(graph_parts)

    return (
        f"⚠️ RESPOND ONLY IN {lang.upper()}. Translate all information to {lang} if needed.\n\n"
        f"User question:\n{q}\n\n"
        f"{fragment_text}\n\n"
        f"{graph_text}\n\n"
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


def _prepend_root_context(
    results: list[dict], workspace_id: str | None,
) -> list[dict]:
    """Fetch root chunks for child results and prepend their content.

    For each result with chunk_type=="child", looks up its parent_id,
    fetches the root chunk from Qdrant, and prepends the root text to
    the child's data/memory fields as context.

    Graceful degradation: if root fetch fails, returns results unchanged.
    """
    # Collect unique parent_ids from child chunks
    parent_ids: dict[str, list[dict]] = {}
    for r in results:
        payload = r.get("payload") or {}
        chunk_type = payload.get("chunk_type", "")
        parent_id = payload.get("parent_id", "")
        if chunk_type == "child" and parent_id:
            parent_ids.setdefault(parent_id, []).append(r)

    if not parent_ids:
        return results

    try:
        from metatron.storage.qdrant import get_hybrid_store
        store = get_hybrid_store(workspace_id)
        root_results = store.fetch_by_chunk_ids(
            list(parent_ids.keys()), workspace_id,
        )
    except Exception:
        logger.warning("search.root_fetch_failed", exc_info=True)
        return results

    # Build lookup: chunk_id → root text
    root_texts: dict[str, str] = {}
    for rr in root_results:
        payload = rr.get("payload") or {}
        chunk_id = payload.get("chunk_id", "")
        text = rr.get("data") or rr.get("memory") or ""
        if chunk_id and text:
            root_texts[chunk_id] = text

    # Prepend root context to child results
    for pid, children in parent_ids.items():
        root_text = root_texts.get(pid)
        if not root_text:
            continue
        prefix = f"[ROOT CONTEXT]\n{root_text}\n\n[DETAIL]\n"
        for child in children:
            for field in ("data", "memory"):
                if child.get(field):
                    child[field] = prefix + child[field]
            # Also update nested payload
            p = child.get("payload") or {}
            for field in ("data", "memory"):
                if p.get(field):
                    p[field] = prefix + p[field]

    return results


@timed("hybrid_search_and_answer")
def hybrid_search_and_answer(  # noqa: C901  # TODO: async migration
    query: str, user_id: str = "user", k: int = 25,
    workspace_id: str | None = None, intent_query: str | None = None,
    return_trace: bool = False,
    plugin_manager=None,
) -> str | dict:
    """End-to-end hybrid search and answer generation."""
    import time
    start_time = time.time()

    raw_query = (intent_query or query or "").strip()
    # Resolve contextual references (relative dates, pronouns) using the full
    # composite query which contains conversation history.  When intent_query
    # is provided (OpenAI-compat), query carries the context we need.
    rq = resolve_query(query.strip() if intent_query and query else raw_query)
    rq_original = raw_query
    use_schema = should_use_team_workflow_schema(rq)
    lang = detect_response_language(rq)

    # Expand query for better BM25 recall (adds status keywords, synonyms)
    eq = expand_query(rq)
    # Translate expanded query for vector/BM25 search if it has Cyrillic
    sq = translate_query_to_english(eq) if _has_cyrillic(eq) else eq

    # -- Classify query intent --
    if _s.query_classifier_enabled:
        # Reuse sq when original == expanded (avoids duplicate LLM translation)
        if _has_cyrillic(rq):
            _translated_for_classifier = sq if rq == eq else translate_query_to_english(rq)
        else:
            _translated_for_classifier = rq
        classification = classify_query(rq, translated_query=_translated_for_classifier)
    else:
        classification = {"profile": "mixed", "confidence": 1.0, "method": "disabled"}

    _profile_weights = get_profile_weights(classification["profile"])

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

    # -- Run 4 recall channels in parallel --
    dense_results, exact_results, metadata_results, graph_results = _run_recall_channels(recall_ctx)

    # -- Merge and deduplicate across channels --
    merged = merge_channels([dense_results, exact_results, metadata_results, graph_results])

    # -- Multi-signal scoring --
    type_cache: dict[str, str] = {}
    for mr in merged:
        type_cache[mr["chunk_id"]] = _result_type(mr["memory"])

    type_counts: dict[str, int] = Counter(type_cache.values())
    total_merged = len(merged)

    _scoring_weights = {k: v for k, v in _profile_weights.items() if k != "blend_weight"}

    for mr in merged:
        mem = mr["memory"]
        date_str = mem.get("date") or (mem.get("payload") or {}).get("date")
        rec = 1.0
        if date_str:
            try:
                dt = datetime.fromisoformat(str(date_str))
                rec = recency_score(dt)
            except (ValueError, TypeError):
                rec = 1.0
        bal = source_balance(type_cache[mr["chunk_id"]], type_counts, total_merged)
        mr["signal_score"] = compute_signal_score(
            channel_scores=mr["channel_scores"],
            recency=rec,
            balance=bal,
            **_scoring_weights,
        )

    # Build score_map keyed by chunk_id (no mutation of memory dicts)
    score_map: dict[str, float] = {
        mr["chunk_id"]: mr.get("signal_score", 0) for mr in merged
    }

    merged.sort(key=lambda x: x.get("signal_score", 0), reverse=True)

    # -- Confidence filter: drop candidates below threshold --
    if _s.min_signal_score > 0:
        merged = [mr for mr in merged if mr.get("signal_score", 0) >= _s.min_signal_score]
        if not merged:
            no_info = "I don't have enough information to answer this question."
            if lang.lower() == "russian":
                no_info = "У меня недостаточно информации для ответа на этот вопрос."
            if return_trace:
                return {
                    "answer": no_info,
                    "source_results": [],
                    "fragments": [],
                    "graph_entities": [],
                    "graph_relations": [],
                    "graph_docs": [],
                    "pipeline_stages": {
                        "original_query": rq_original,
                        "resolved_query": rq if rq != rq_original else None,
                        "translated_query": sq,
                        "expanded_query": eq,
                        "detected_language": lang,
                        "recall_dense_count": len(dense_results),
                        "recall_exact_count": len(exact_results),
                        "recall_metadata_count": len(metadata_results),
                        "recall_graph_count": len(graph_results),
                        "recall_total_unique": 0,
                        "pre_rerank_count": 0,
                        "post_rerank_count": 0,
                        "signal_scored_count": total_merged,
                        "rerank_pool_count": 0,
                        "fragment_count": 0,
                        "primary_fragment_count": 0,
                        "supporting_fragment_count": 0,
                        "token_budget_used": 0,
                        "query_profile": classification["profile"],
                        "query_profile_method": classification["method"],
                        "query_profile_confidence": classification["confidence"],
                    },
                    "retrieved_doc_labels": [],
                }
            return no_info

    pool_size = _s.rerank_pool_size if _s.reranker_enabled else len(merged)
    base = [mr["memory"] for mr in merged[:pool_size]]

    _pre_rerank_count = len(base)
    if _s.reranker_enabled:
        from metatron.retrieval.reranker import rerank
        base = rerank(query=rq, results=base, top_k=len(base))
        normalize_rerank_scores(base)
        for r in base:
            cid = str(r.get("id", ""))
            score_map[cid] = compute_final_score(
                signal_score=score_map.get(cid, 0),
                rerank_score=r.get("rerank_score", 0),
                blend_weight=_profile_weights["blend_weight"],
            )
        base.sort(
            key=lambda x: score_map.get(str(x.get("id", "")), 0),
            reverse=True,
        )
    base = base[:k]
    _post_rerank_count = len(base)

    # -- Hierarchical chunking: prepend root chunk content to child chunks --
    if _s.hierarchical_chunking_enabled:
        base = _prepend_root_context(base, workspace_id)

    # -- ACL post-rerank: defense-in-depth filter --
    if plugin_manager:
        ctx = _run_hooks_sync(plugin_manager, "search_post_rerank", {
            "chunks": base, "user_id": user_id, "workspace_id": workspace_id,
        })
        base = ctx.get("chunks", base)

    frags, seen_h, total_c, doc_stats = _collect_frags(base, set(), 0)
    _mark_evidence_role(frags, classification["profile"])

    # -- Graph enrichment (graceful degradation: continue without graph if unavailable) --
    g_ents: list = []
    g_rels: list = []
    g_docs: list = []
    try:
        dl = _doc_labels(base)
        frag_texts = [f["text"] for f in frags]
        g_ents = get_entities_by_doc_labels(dl, workspace_id) if dl else get_graph_entities(frag_texts, workspace_id)
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
        _token_budget_used = sum(len(f["text"]) for f in frags) // 4 if frags else 0
        result = {
            "answer": _append_sources(answer, base),
            "source_results": base,
            "fragments": frags,
            "graph_entities": g_ents,
            "graph_relations": g_rels,
            "graph_docs": g_docs,
            "pipeline_stages": {
                "original_query": rq_original,
                "resolved_query": rq if rq != rq_original else None,
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
                "signal_scored_count": total_merged,
                "rerank_pool_count": pool_size,
                "fragment_count": len(frags),
                "primary_fragment_count": sum(
                    1 for f in frags if f.get("evidence_marker") == "PRIMARY"
                ),
                "supporting_fragment_count": sum(
                    1 for f in frags if f.get("evidence_marker") != "PRIMARY"
                ),
                "token_budget_used": _token_budget_used,
                "query_profile": classification["profile"],
                "query_profile_method": classification["method"],
                "query_profile_confidence": classification["confidence"],
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
            source_word_count = sum(len(f["text"].split()) for f in frags) if frags else 0
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
