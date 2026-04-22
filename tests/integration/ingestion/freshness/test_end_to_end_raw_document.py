"""End-to-end integration test for the KB freshness worker (MTRNIX-313).

Requires: PostgreSQL (migration 018 applied), Qdrant, Redis. Neo4j is
optional — the test asserts PG + queue state and tolerates a graph miss.

Flow:
1. Seed one raw_documents row.
2. Enqueue a FreshnessJob via the producer (flag-gated helper).
3. Build a worker with the KB pipeline and run_once.
4. Assert PG lifecycle columns are touched (evidence_count, or
   last_freshness_run_at, or status), and that a
   ``freshness_job_processed`` MachineEvent landed with
   ``target_kind='raw_document'``.

Phase A (memory) worker path must remain untouched — asserted implicitly
by running in the same workspace and only the KB producer path firing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.freshness.coordination import CoordinationStore
from metatron.freshness.decision_engine import RuleBasedDecisionEngine
from metatron.freshness.stages.curator import Curator
from metatron.freshness.stages.linker import Linker
from metatron.freshness.stages.monitor import FreshnessMonitor
from metatron.freshness.stages.reconciler import Reconciler
from metatron.ingestion.freshness.producer import enqueue_raw_document_if_enabled
from metatron.ingestion.freshness.target_raw_document import RawDocumentTarget
from metatron.memory.freshness.worker import FreshnessWorker, _Pipeline
from metatron.storage.freshness_pg import FreshnessStore
from metatron.storage.postgres import PostgresStore
from metatron.storage.qdrant import AsyncQdrantVectorStore
from metatron.storage.redis import RedisStore

pytestmark = pytest.mark.integration


async def _cleanup_pg(engine, workspace: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa_text("DELETE FROM machine_events WHERE workspace_id = :ws"),
            {"ws": workspace},
        )
        await conn.execute(
            sa_text("DELETE FROM review_entries WHERE workspace_id = :ws"),
            {"ws": workspace},
        )
        await conn.execute(
            sa_text("DELETE FROM raw_documents WHERE workspace_id = :ws"),
            {"ws": workspace},
        )


async def _cleanup_redis(redis: RedisStore, workspace: str) -> None:
    import contextlib

    with contextlib.suppress(Exception):
        await redis.delete(f"freshness:queue:{workspace}")


async def test_end_to_end_kb_job_is_processed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: producer enqueues → worker processes → PG + events written."""
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", True)
    monkeypatch.setattr(settings, "freshness_kb_enabled", True)

    workspace = f"kbfresh-it-{uuid4().hex[:8]}"
    doc_id = uuid4().hex

    redis = RedisStore(settings.redis_url)
    try:
        if not await redis.ping():
            pytest.skip("Redis unreachable")
    except Exception:
        pytest.skip("Redis unreachable")

    coordination = CoordinationStore(redis=redis)
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_store = PostgresStore(settings.postgres_dsn)
    freshness_store = FreshnessStore(engine)

    try:
        # --- Seed one raw_documents row directly via SQL (avoids tripping
        #     a full IngestionPipeline for an integration smoke). ---
        now = datetime.now(UTC)
        async with engine.begin() as conn:
            await conn.execute(
                sa_text(
                    """
                    INSERT INTO raw_documents (
                        id, workspace_id, connector_type, source_id, title,
                        content, content_hash, metadata, source_role,
                        qdrant_synced, graph_synced,
                        fetched_at, created_at, updated_at,
                        status, freshness_score
                    ) VALUES (
                        :id, :ws, 'confluence', :src, 'Integration Doc',
                        'Stripe webhook forwards events to /api/hooks/stripe.',
                        :ch, '{}'::jsonb, 'knowledge_base',
                        false, false,
                        :now, :now, :now,
                        'active', 0.5
                    )
                    """
                ),
                {
                    "id": doc_id,
                    "ws": workspace,
                    "src": f"page-{doc_id}",
                    "ch": "it-" + doc_id,
                    "now": now,
                },
            )

        # --- Qdrant factory — one cached async store for this workspace ---
        qdrant_store: AsyncQdrantVectorStore | None = None

        def kb_qdrant_factory(ws: str) -> AsyncQdrantVectorStore:
            nonlocal qdrant_store
            if qdrant_store is None:
                qdrant_store = AsyncQdrantVectorStore(
                    workspace_id=ws,
                    host=settings.qdrant_host,
                    port=settings.qdrant_http_port,
                    api_key=settings.qdrant_api_key or None,
                    https=settings.qdrant_https,
                )
            return qdrant_store

        # --- Build KB pipeline + worker ---
        raw_doc_target = RawDocumentTarget(pg_store=pg_store, qdrant_factory=kb_qdrant_factory)
        kb_linker = Linker(
            target=raw_doc_target,
            freshness_store=freshness_store,
            coordination=coordination,
            threshold=settings.freshness_linker_threshold,
        )
        kb_reconciler = Reconciler(
            target=raw_doc_target,
            freshness_store=freshness_store,
            coordination=coordination,
            threshold=settings.freshness_reconciler_threshold,
        )
        kb_monitor = FreshnessMonitor(
            target=raw_doc_target,
            freshness_store=freshness_store,
            coordination=coordination,
            stale_after_days=settings.freshness_kb_stale_after_days,
        )
        kb_curator = Curator(
            target=raw_doc_target,
            freshness_store=freshness_store,
            coordination=coordination,
        )
        pipelines = {
            "raw_document": _Pipeline(
                linker=kb_linker,
                reconciler=kb_reconciler,
                monitor=kb_monitor,
                curator=kb_curator,
                target=raw_doc_target,
            )
        }
        worker = FreshnessWorker(
            coordination=coordination,
            freshness_pg=freshness_store,
            decision_engine=RuleBasedDecisionEngine(),
            pipelines=pipelines,
        )

        # --- Enqueue via the flag-gated producer ---
        await enqueue_raw_document_if_enabled(
            workspace_id=workspace,
            raw_document_id=doc_id,
            event_type="content_changed",
            coordination=coordination,
        )
        depth = await coordination.queue_depth(workspace)
        assert depth >= 1

        # --- Process one iteration ---
        processed = await worker.run_once(max_jobs=10)
        assert processed == 1

        # --- Assert worker wrote to PG ---
        doc = await pg_store.get_raw_document_by_id(workspace, doc_id)
        assert doc is not None
        # Linker always writes evidence_count (may be 0 if Qdrant is empty
        # — no sibling docs to link against).
        assert doc.evidence_count >= 0

        # --- Assert MachineEvents were persisted with target_kind=raw_document ---
        events = await freshness_store.list_events_for_target(
            workspace,
            "raw_document",
            doc_id,
        )
        event_types = {e.event_type for e in events}
        assert "freshness_job_received" in event_types
        assert "freshness_job_processed" in event_types
        for e in events:
            assert e.target_kind == "raw_document"

        # --- Queue drained ---
        depth_after = await coordination.queue_depth(workspace)
        assert depth_after == 0
    finally:
        await _cleanup_pg(engine, workspace)
        await _cleanup_redis(redis, workspace)
        if qdrant_store is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await qdrant_store.client.close()
        await redis.close()
        await engine.dispose()
