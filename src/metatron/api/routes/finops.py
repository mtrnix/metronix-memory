"""FinOps API — time savings metrics for the knowledge base.

Quantifies how much reading time Metatron saves compared to manual search.

Time savings formula (per query):
    manual_reading_time  = (source_word_count / WPM) * SEARCH_OVERHEAD
    metatron_time        = total_ms / 60_000
    time_saved_minutes   = max(0, manual_reading_time - metatron_time)

Constants:
    WPM = 150        — average adult reading speed (words per minute)
    SEARCH_OVERHEAD = 1.5  — multiplier for time spent locating the right docs

source_word_count is stored in query_traces.trace JSONB by hybrid_search_and_answer().
Older traces without this field are treated as 0 words (no savings credited).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/finops", tags=["finops"])

# ---------------------------------------------------------------------------
# Formula constants
# ---------------------------------------------------------------------------

_WPM: int = 150          # average reading speed (words per minute)
_SEARCH_OVERHEAD: float = 1.5  # multiplier for time spent finding the right docs


def _time_saved_minutes(word_count: int, total_ms: float) -> float:
    """Compute time saved (minutes) for a single query.

    Args:
        word_count: Total words in source fragments sent to LLM context.
        total_ms: Metatron response latency in milliseconds.

    Returns:
        Minutes saved (floored at 0 — never negative).
    """
    manual_minutes = (word_count / _WPM) * _SEARCH_OVERHEAD
    metatron_minutes = total_ms / 60_000
    return max(0.0, manual_minutes - metatron_minutes)


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

    from metatron.storage.pg_connection import get_session
    from metatron.storage.pg_models import QueryTraceRow

    try:
        with get_session() as session:
            orm_rows = session.execute(
                select(QueryTraceRow)
                .where(
                    QueryTraceRow.workspace_id == workspace_id,
                    QueryTraceRow.created_at >= since,
                )
                .order_by(QueryTraceRow.created_at)
            ).scalars().all()
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
            created_at.date().isoformat()
            if created_at is not None
            else date.today().isoformat()
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
    start_date = (today - timedelta(days=days - 1))
    all_dates: list[dict] = []
    cursor = start_date
    while cursor <= today:
        ds = cursor.isoformat()
        all_dates.append(daily.get(ds, {"date": ds, "queries": 0, "time_saved_minutes": 0.0}))
        cursor += timedelta(days=1)

    return {
        "total_queries": total_queries,
        "total_time_saved_minutes": round(total_time_saved, 2),
        "avg_time_saved_per_query_minutes": round(
            total_time_saved / total_queries, 2
        ) if total_queries else 0.0,
        "avg_response_time_ms": round(
            total_ms_sum / total_queries, 1
        ) if total_queries else 0.0,
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

    Calculates how many minutes of manual reading/searching Metatron
    saved by surfacing the right information automatically.

    Formula per query:
        manual_reading_time  = (source_word_count / 150 WPM) * 1.5 search overhead
        metatron_time        = total_ms / 60 000  (ms → minutes)
        time_saved_minutes   = max(0, manual_reading_time - metatron_time)

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
