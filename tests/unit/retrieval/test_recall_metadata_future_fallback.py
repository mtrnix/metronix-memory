"""M6 future-date fallback guard on the ASYNC metadata channel (MTRNIX-397).

recall_metadata_async is the production path (hybrid_search_and_answer is async). The guard
must only fire for FUTURE-dated queries with no hits — a historical empty-date query must NOT
fall back to recent in-progress items. (A sync/async divergence here slipped a real bug.)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from metronix.retrieval.channels import RecallContext, recall_metadata_async


def _ctx(dates: tuple[str, ...], *, fallback: bool) -> RecallContext:
    return RecallContext(
        original_query="q",
        translated_query="q",
        expanded_query="q",
        detected_language="en",
        workspace_id="TEST",
        access_filter=None,
        settings=SimpleNamespace(
            recall_top_n_metadata=10,
            retrieval_future_date_fallback_enabled=fallback,
        ),
        extracted_jira_keys=[],
        extracted_title_entities=[],
        extracted_dates=dates,
        detected_person=[],
        is_activity_query=False,  # force the M6 elif (not the activity status branch)
    )


def _store() -> AsyncMock:
    s = AsyncMock()
    s.search_by_date = AsyncMock(return_value=[])  # no write-date / due-date hits
    s.search_by_status = AsyncMock(return_value=[])  # the fallback target
    s.search_by_assignee = AsyncMock(return_value=[])
    return s


async def test_future_date_no_hits_triggers_fallback() -> None:
    store = _store()
    with patch(
        "metronix.retrieval.channels.get_async_hybrid_store", AsyncMock(return_value=store)
    ):
        await recall_metadata_async(_ctx(("2099-01-01",), fallback=True))
    store.search_by_status.assert_called()  # future + no hits + flag on → fallback fires


async def test_historical_date_no_hits_does_not_fallback() -> None:
    store = _store()
    with patch(
        "metronix.retrieval.channels.get_async_hybrid_store", AsyncMock(return_value=store)
    ):
        await recall_metadata_async(_ctx(("2020-01-01",), fallback=True))
    store.search_by_status.assert_not_called()  # historical date → NO fallback (the bug)


async def test_future_date_fallback_off_by_default() -> None:
    store = _store()
    with patch(
        "metronix.retrieval.channels.get_async_hybrid_store", AsyncMock(return_value=store)
    ):
        await recall_metadata_async(_ctx(("2099-01-01",), fallback=False))
    store.search_by_status.assert_not_called()  # flag off → never fallback
