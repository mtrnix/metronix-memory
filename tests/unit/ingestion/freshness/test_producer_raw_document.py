"""enqueue_raw_document_if_enabled — flag-off, flag-on, fail-soft (MTRNIX-313)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from metatron.ingestion.freshness.producer import enqueue_raw_document_if_enabled


async def test_noop_when_master_flag_off() -> None:
    settings = MagicMock(freshness_enabled=False, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()

    with patch(
        "metatron.ingestion.freshness.producer.get_settings",
        return_value=settings,
    ):
        await enqueue_raw_document_if_enabled(
            "ws",
            "doc-1",
            "knowledge_changed",
            coordination=coord,
        )

    coord.enqueue_job.assert_not_awaited()


async def test_noop_when_kb_flag_off() -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=False)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()

    with patch(
        "metatron.ingestion.freshness.producer.get_settings",
        return_value=settings,
    ):
        await enqueue_raw_document_if_enabled(
            "ws",
            "doc-1",
            "knowledge_changed",
            coordination=coord,
        )

    coord.enqueue_job.assert_not_awaited()


async def test_noop_on_empty_workspace_or_id() -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()

    with patch(
        "metatron.ingestion.freshness.producer.get_settings",
        return_value=settings,
    ):
        await enqueue_raw_document_if_enabled("", "doc-1", coordination=coord)
        await enqueue_raw_document_if_enabled("ws", "", coordination=coord)

    coord.enqueue_job.assert_not_awaited()


async def test_enqueues_job_with_target_kind_raw_document() -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()

    with patch(
        "metatron.ingestion.freshness.producer.get_settings",
        return_value=settings,
    ):
        await enqueue_raw_document_if_enabled(
            "ws",
            "doc-1",
            "content_changed",
            coordination=coord,
        )

    coord.enqueue_job.assert_awaited_once()
    job = coord.enqueue_job.await_args.args[0]
    assert job.workspace_id == "ws"
    assert job.target_kind == "raw_document"
    assert job.target_id == "doc-1"
    assert job.event_type == "content_changed"


async def test_swallows_redis_errors() -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch(
        "metatron.ingestion.freshness.producer.get_settings",
        return_value=settings,
    ):
        # Must not raise — producer is fail-soft so KB ingestion keeps working
        # even when the freshness queue is down.
        await enqueue_raw_document_if_enabled(
            "ws",
            "doc-1",
            "knowledge_changed",
            coordination=coord,
        )


async def test_payload_forwarded_when_provided() -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()

    with patch(
        "metatron.ingestion.freshness.producer.get_settings",
        return_value=settings,
    ):
        await enqueue_raw_document_if_enabled(
            "ws",
            "doc-1",
            "content_changed",
            coordination=coord,
            payload={"connector_type": "confluence"},
        )

    job = coord.enqueue_job.await_args.args[0]
    assert job.payload == {"connector_type": "confluence"}
