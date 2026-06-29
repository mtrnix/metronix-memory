"""FinOps API — time savings metrics for the knowledge base.

Quantifies how much reading time Metronix saves compared to manual search.

Time savings formula (per query):
    manual_reading_time  = (source_word_count / WPM) * SEARCH_OVERHEAD
    metronix_time        = total_ms / 60_000
    time_saved_minutes   = max(0, manual_reading_time - metronix_time)

Constants:
    WPM = 150        — average adult reading speed (words per minute)
    SEARCH_OVERHEAD = 1.5  — multiplier for time spent locating the right docs

source_word_count is stored in query_traces.trace JSONB by hybrid_search_and_answer().
Older traces without this field are treated as 0 words (no savings credited).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/finops", tags=["finops"])

# ---------------------------------------------------------------------------
# Formula constants
# ---------------------------------------------------------------------------

_WPM: int = 150  # average reading speed (words per minute)
_SEARCH_OVERHEAD: float = 1.5  # multiplier for time spent finding the right docs


def _time_saved_minutes(word_count: int, total_ms: float) -> float:
    """Compute time saved (minutes) for a single query.

    Args:
        word_count: Total words in source fragments sent to LLM context.
        total_ms: Metronix response latency in milliseconds.

    Returns:
        Minutes saved (floored at 0 — never negative).
    """
    manual_minutes = (word_count / _WPM) * _SEARCH_OVERHEAD
    metronix_minutes = total_ms / 60_000
    return max(0.0, manual_minutes - metronix_minutes)


# ---------------------------------------------------------------------------
# Storage query (sync, runs in thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _fetch_time_savings(workspace_id: str, since: datetime, days: int) -> dict:
    """Aggregate time-savings data from query_traces for a workspace.

    Args:
        workspace_id: Workspace to query.
        since: Lower bound for created_at (UTC-aware).
        days: Lookback window, used only to populate missing dates in breakdown.

    Returns:
        Aggregated stats dict matching TimeSavingsResponse schema.
    """
    from sqlalchemy import select

    from metronix.storage.pg_connection import get_session
    from metronix.storage.pg_models import QueryTraceRow

    try:
        with get_session() as session:
            orm_rows = (
                session.execute(
                    select(QueryTraceRow)
                    .where(
                        QueryTraceRow.workspace_id == workspace_id,
                        QueryTraceRow.created_at >= since,
                    )
                    .order_by(QueryTraceRow.created_at)
                )
                .scalars()
                .all()
            )
            # Convert to plain dicts while the session is still open.
            # Accessing JSONB columns (row.trace) after session close raises
            # DetachedInstanceError — dicts are safe to use outside the block.
            traces = [
                {
                    "total_ms": row.total_ms,
                    "trace": dict(row.trace or {}),
                    "created_at": row.created_at,
                }
                for row in orm_rows
            ]
    except Exception as exc:
        logger.warning("finops.time_savings.db_error", workspace_id=workspace_id, error=str(exc))
        traces = []

    # --- Aggregate per-query and per-day ---
    total_time_saved = 0.0
    total_words = 0
    total_ms_sum = 0.0
    daily: dict[str, dict] = {}

    for row in traces:
        # COALESCE: source_word_count absent in traces written before this feature
        word_count = int(row["trace"].get("source_word_count", 0))
        saved = _time_saved_minutes(word_count, row["total_ms"])

        created_at = row["created_at"]
        date_str = (
            created_at.date().isoformat() if created_at is not None else date.today().isoformat()
        )
        if date_str not in daily:
            daily[date_str] = {"date": date_str, "queries": 0, "time_saved_minutes": 0.0}
        daily[date_str]["queries"] += 1
        daily[date_str]["time_saved_minutes"] = round(
            daily[date_str]["time_saved_minutes"] + saved, 2
        )

        total_time_saved += saved
        total_words += word_count
        total_ms_sum += row["total_ms"]

    total_queries = len(traces)

    # Fill gaps so every calendar date in the range appears in the breakdown
    today = date.today()
    start_date = today - timedelta(days=days - 1)
    all_dates: list[dict] = []
    cursor = start_date
    while cursor <= today:
        ds = cursor.isoformat()
        all_dates.append(daily.get(ds, {"date": ds, "queries": 0, "time_saved_minutes": 0.0}))
        cursor += timedelta(days=1)

    return {
        "total_queries": total_queries,
        "total_time_saved_minutes": round(total_time_saved, 2),
        "avg_time_saved_per_query_minutes": round(total_time_saved / total_queries, 2)
        if total_queries
        else 0.0,
        "avg_response_time_ms": round(total_ms_sum / total_queries, 1) if total_queries else 0.0,
        "total_source_words_processed": total_words,
        "daily_breakdown": all_dates,
    }


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class DailyBreakdown(BaseModel):
    date: str
    queries: int
    time_saved_minutes: float


class TimeSavingsResponse(BaseModel):
    """Time savings aggregation for a workspace over a date range."""

    period_days: int
    total_queries: int
    total_time_saved_minutes: float
    avg_time_saved_per_query_minutes: float
    avg_response_time_ms: float
    total_source_words_processed: int
    daily_breakdown: list[DailyBreakdown]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/time-savings", response_model=TimeSavingsResponse)
async def get_time_savings(
    workspace_id: str = Query(..., description="Workspace ID"),
    days: int = Query(default=30, ge=1, le=365, description="Lookback period in days"),
) -> TimeSavingsResponse:
    """Aggregate time savings from query traces.

    Calculates how many minutes of manual reading/searching Metronix
    saved by surfacing the right information automatically.

    Formula per query:
        manual_reading_time  = (source_word_count / 150 WPM) * 1.5 search overhead
        metronix_time        = total_ms / 60 000  (ms → minutes)
        time_saved_minutes   = max(0, manual_reading_time - metronix_time)

    Queries without source_word_count (written before this feature) count as 0 savings.

    Args:
        workspace_id: Workspace to compute savings for.
        days: Number of calendar days to look back (1–365, default 30).

    Returns:
        Aggregated stats and per-day breakdown.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    data = await asyncio.to_thread(_fetch_time_savings, workspace_id, since, days)

    return TimeSavingsResponse(
        period_days=days,
        **data,
    )


# ---------------------------------------------------------------------------
# Active users — storage query (sync, runs in thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


# Must match the ``call_site`` string that retrieval/search.py passes when it
# logs the RAG synthesis LLM call to llm_generation_log. There is no shared
# constant: search.py lives at L2 and cannot import upward into this L6 module,
# so this coupling is by literal value. A rename there without updating this
# constant silently makes the metric return 0 — grep both sites on any change.
_RAG_ANSWER_CALL_SITE = "rag_answer"
_USER_FACING_SOURCES = ("oai_compat", "rest")


class ActiveUsersCounts(NamedTuple):
    """Result of :func:`_fetch_active_users` — named to prevent positional swap."""

    active_users: int
    period_queries: int


def _fetch_active_users(workspace_id: str, since: datetime) -> ActiveUsersCounts:
    """Count distinct users and total queries that reached rag_answer in window.

    Reads ``llm_generation_log`` (MTRNIX-336), filtering to user-facing RAG
    completions only (``source IN ('oai_compat', 'rest')`` and
    ``call_site = 'rag_answer'``). MCP traffic is excluded by source filter;
    ingestion/freshness/benchmark traffic is excluded both by source and by
    ``user_id IS NULL``.

    Opt-out note: workspaces with ``llm_telemetry_opt_out=true`` are NOT
    filtered here. The exclusion happens upstream at write time
    (``llm/telemetry.py`` skips the INSERT), so a workspace that has been
    opted out from the start has no rows and returns ``(0, 0)``. A workspace
    that toggles opt-out ON *after* accumulating rows will still count those
    pre-opt-out rows — this query has no JOIN to ``workspaces`` and does not
    retroactively hide them.

    Returns ``ActiveUsersCounts(active_users, period_queries)``. Both are 0 on
    any DB exception (graceful degradation — dashboard cards never break the
    page).
    """
    from sqlalchemy import func, select

    from metronix.storage.pg_connection import get_session
    from metronix.storage.pg_models import LLMGenerationLogRow

    try:
        with get_session() as session:
            stmt = select(
                func.count(func.distinct(LLMGenerationLogRow.user_id)).label("active_users"),
                func.count().label("period_queries"),
            ).where(
                LLMGenerationLogRow.workspace_id == workspace_id,
                # NOT NULL is redundant for COUNT(DISTINCT user_id) (PG ignores NULLs in
                # aggregates) but REQUIRED for COUNT(*) AS period_queries: without it,
                # anonymous rows would inflate the numerator of Avg = period_queries /
                # active_users while contributing nothing to the denominator. Do not drop.
                LLMGenerationLogRow.user_id.isnot(None),
                LLMGenerationLogRow.source.in_(_USER_FACING_SOURCES),
                LLMGenerationLogRow.call_site == _RAG_ANSWER_CALL_SITE,
                LLMGenerationLogRow.created_at >= since,
            )
            row = session.execute(stmt).one()
            return ActiveUsersCounts(int(row.active_users or 0), int(row.period_queries or 0))
    except Exception as exc:
        logger.warning(
            "finops.active_users.db_error",
            workspace_id=workspace_id,
            error=str(exc),
        )
        return ActiveUsersCounts(0, 0)


# ---------------------------------------------------------------------------
# Active users — response model
# ---------------------------------------------------------------------------


class ActiveUsersResponse(BaseModel):
    """Active users + total queries from the same filtered slice.

    Both numbers come from the same source (llm_generation_log) and the same
    filter (source IN ('oai_compat','rest'), call_site='rag_answer',
    user_id IS NOT NULL), so the frontend can compute
    Avg Queries/User = period_queries / active_users from a self-consistent
    slice instead of mixing this endpoint with /finops/time-savings.
    """

    period_days: int
    active_users: int
    period_queries: int


# ---------------------------------------------------------------------------
# Active users — endpoint
# ---------------------------------------------------------------------------


@router.get("/active-users", response_model=ActiveUsersResponse)
async def get_active_users(
    workspace_id: str = Query(..., description="Workspace ID"),
    days: int = Query(default=30, ge=1, le=365, description="Lookback period in days"),
) -> ActiveUsersResponse:
    """Count distinct users who reached rag_answer in window + total queries.

    Backs the Unique Users and Avg Queries/User dashboard cards. Returns the
    count of distinct authenticated users who completed a RAG answer
    (``call_site='rag_answer'``) via OpenAI-compat (``/v1/chat/completions``)
    or REST (``/api/v1/chat``) in the requested window, plus the total query
    count from the same filtered slice. MCP traffic and system traffic
    (ingestion/freshness/benchmark) are excluded by design.

    Returns 0 for both fields on empty results, unknown workspace_id, DB
    errors, or workspaces with ``llm_telemetry_opt_out=true``.

    Note on "user" semantics: the count is over distinct authenticated
    principals (whatever populates the ``user_id`` column at the request
    entry point). An external agent runtime (Hermes, etc.) authenticating
    via OpenAI-compat with a single service-account API key counts as ONE
    user even if it serves many humans. The dashboard label "Unique Users"
    should be read as "unique authenticated principals", not "unique
    humans".
    """
    since = datetime.now(UTC) - timedelta(days=days)
    active_users, period_queries = await asyncio.to_thread(
        _fetch_active_users, workspace_id, since
    )

    return ActiveUsersResponse(
        period_days=days,
        active_users=active_users,
        period_queries=period_queries,
    )


# ---------------------------------------------------------------------------
# Cost savings — constants (reviewed quarterly, last updated March 2026)
# ---------------------------------------------------------------------------

_TOKENS_PER_WORD: float = 1.6  # mixed English/Russian average
_AVG_OUTPUT_TOKENS: int = 500  # typical RAG answer length
_INFRA_COST_PER_QUERY: float = 0.0005  # self-hosted marginal cost (~$0.50/1000 queries)

# Provider pricing: $/1M tokens (input, output)
_PROVIDER_PRICING: dict[str, dict] = {
    "openai_gpt4o": {"label": "GPT-4o", "input": 2.50, "output": 10.00},
    "anthropic_sonnet": {"label": "Claude Sonnet 4.6", "input": 3.00, "output": 15.00},
    "google_gemini": {"label": "Gemini 2.5 Pro", "input": 1.25, "output": 10.00},
}


def _calculate_doc_costs(total_context_words: int, fetch_count: int) -> dict[str, float]:
    """Calculate commercial API cost per provider for a document.

    Returns:
        {provider_key: total_cost_usd}
    """
    if fetch_count == 0:
        return {k: 0.0 for k in _PROVIDER_PRICING}

    input_tokens = total_context_words * _TOKENS_PER_WORD
    costs = {}
    for key, pricing in _PROVIDER_PRICING.items():
        cost = (input_tokens * pricing["input"] / 1_000_000) + (
            _AVG_OUTPUT_TOKENS * pricing["output"] / 1_000_000 * fetch_count
        )
        costs[key] = round(cost, 6)
    return costs


def _metronix_cost(fetch_count: int) -> float:
    """Calculate Metronix infrastructure cost."""
    return _INFRA_COST_PER_QUERY * fetch_count


# ---------------------------------------------------------------------------
# Cost savings — storage query (sync, runs in thread)
# ---------------------------------------------------------------------------


def _fetch_cost_savings(workspace_id: str, since_date: date, limit: int) -> dict:
    """Aggregate cost savings from document_fetch_stats for a workspace."""
    from sqlalchemy import func, select

    from metronix.storage.pg_connection import get_session
    from metronix.storage.pg_models import DocumentFetchStatsRow

    try:
        with get_session() as session:
            base_stmt = (
                select(
                    DocumentFetchStatsRow.doc_label,
                    func.max(DocumentFetchStatsRow.title).label("title"),
                    func.sum(DocumentFetchStatsRow.fetch_count).label("fetch_count"),
                    func.sum(DocumentFetchStatsRow.total_context_words).label(
                        "total_context_words"
                    ),
                )
                .where(
                    DocumentFetchStatsRow.workspace_id == workspace_id,
                    DocumentFetchStatsRow.fetch_date >= since_date,
                )
                .group_by(DocumentFetchStatsRow.doc_label)
                .order_by(func.sum(DocumentFetchStatsRow.fetch_count).desc())
            )
            all_rows = session.execute(base_stmt).all()
            all_docs = [
                {
                    "doc_label": r.doc_label,
                    "title": r.title or "",
                    "fetch_count": int(r.fetch_count or 0),
                    "total_context_words": int(r.total_context_words or 0),
                }
                for r in all_rows
            ]
    except Exception as exc:
        logger.warning("finops.cost_savings.db_error", workspace_id=workspace_id, error=str(exc))
        all_docs = []

    # Calculate costs for ALL documents (accurate totals)
    total_fetches = 0
    total_metronix = 0.0
    provider_totals: dict[str, float] = {k: 0.0 for k in _PROVIDER_PRICING}

    for doc in all_docs:
        fc = doc["fetch_count"]
        tcw = doc["total_context_words"]
        costs = _calculate_doc_costs(tcw, fc)
        mc = _metronix_cost(fc)
        total_fetches += fc
        total_metronix += mc
        for k, c in costs.items():
            provider_totals[k] += c

    # Build top_documents (limited)
    top_documents = []
    for doc in all_docs[:limit]:
        fc = doc["fetch_count"]
        tcw = doc["total_context_words"]
        costs = _calculate_doc_costs(tcw, fc)
        mc = _metronix_cost(fc)
        max_savings = max((c - mc) for c in costs.values()) if costs else 0.0

        top_documents.append(
            {
                "doc_label": doc["doc_label"],
                "title": doc["title"],
                "fetch_count": fc,
                "total_context_words": tcw,
                "costs": {k: round(v, 4) for k, v in costs.items()},
                "metronix_cost": round(mc, 4),
                "max_savings": round(max_savings, 4),
            }
        )

    # Build summary
    providers_summary = {}
    for k, pricing in _PROVIDER_PRICING.items():
        commercial = provider_totals[k]
        savings = commercial - total_metronix
        providers_summary[k] = {
            "label": pricing["label"],
            "commercial_cost": round(commercial, 4),
            "savings": round(savings, 4),
            "savings_pct": round((savings / commercial * 100), 1) if commercial > 0 else 0.0,
        }

    return {
        "summary": {
            "total_documents": len(all_docs),
            "total_fetches": total_fetches,
            "metronix_cost": round(total_metronix, 4),
            "providers": providers_summary,
        },
        "top_documents": top_documents,
    }


# ---------------------------------------------------------------------------
# Cost savings — response models
# ---------------------------------------------------------------------------


class ProviderCostSummary(BaseModel):
    label: str
    commercial_cost: float
    savings: float
    savings_pct: float


class CostSavingsSummary(BaseModel):
    total_documents: int
    total_fetches: int
    metronix_cost: float
    providers: dict[str, ProviderCostSummary]


class DocumentCostEntry(BaseModel):
    doc_label: str
    title: str
    fetch_count: int
    total_context_words: int
    costs: dict[str, float]
    metronix_cost: float
    max_savings: float


class CostSavingsResponse(BaseModel):
    period_days: int
    summary: CostSavingsSummary
    top_documents: list[DocumentCostEntry]


# ---------------------------------------------------------------------------
# Cost savings — endpoint
# ---------------------------------------------------------------------------


@router.get("/cost-savings", response_model=CostSavingsResponse)
async def get_cost_savings(
    workspace_id: str = Query(..., description="Workspace ID"),
    days: int = Query(default=30, ge=1, le=365, description="Lookback period in days"),
    limit: int = Query(default=20, ge=1, le=100, description="Top N documents"),
) -> CostSavingsResponse:
    """Cost savings comparison: Metronix vs commercial LLM APIs.

    Compares self-hosted RAG cost against GPT-4o, Claude Sonnet 4.6,
    and Gemini 2.5 Pro for the most frequently retrieved documents.
    """
    since_date = date.today() - timedelta(days=days)
    data = await asyncio.to_thread(_fetch_cost_savings, workspace_id, since_date, limit)

    return CostSavingsResponse(
        period_days=days,
        **data,
    )
