"""Worker dispatches jobs by target_kind (MTRNIX-313).

With Phase B the worker hosts two pipeline stacks (memory + KB) behind a
``pipelines: dict[target_kind, _Pipeline]`` map. These tests verify:

1. An unknown ``target_kind`` drains the queue (counts as processed) but
   logs a poison-skip MachineEvent and never invokes a stage.
2. A memory job routes to the memory pipeline.
3. A KB job routes to the KB pipeline — even when memory and KB pipelines
   are both present in the worker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import FreshnessJob
from metatron.memory.freshness.worker import FreshnessWorker, _Pipeline


def _pipeline_stub(kind: str) -> _Pipeline:
    target = MagicMock()
    target.kind = kind
    target.supports_candidate_promotion = kind == "memory_record"
    target.get = AsyncMock(return_value=None)
    linker = AsyncMock()
    reconciler = AsyncMock()
    monitor = AsyncMock()
    curator = AsyncMock()
    for stage in (linker, reconciler, monitor, curator):
        stage.run = AsyncMock(return_value=None)
    return _Pipeline(
        linker=linker,
        reconciler=reconciler,
        monitor=monitor,
        curator=curator,
        target=target,
    )


def _make_worker(
    *,
    pipelines: dict[str, _Pipeline] | None = None,
) -> tuple[FreshnessWorker, AsyncMock, AsyncMock]:
    coord = AsyncMock()
    coord.list_active_workspaces = AsyncMock(return_value=["ws"])
    coord.queue_depth = AsyncMock(return_value=0)
    freshness_pg = AsyncMock()
    decision_engine = AsyncMock()
    worker = FreshnessWorker(
        coordination=coord,
        freshness_pg=freshness_pg,
        decision_engine=decision_engine,
        pipelines=pipelines or {},
    )
    return worker, coord, freshness_pg


async def test_unknown_target_kind_drains_queue_without_running_stages() -> None:
    worker, coord, fpg = _make_worker(pipelines={})
    coord.dequeue_batch = AsyncMock(
        return_value=[
            FreshnessJob(
                workspace_id="ws",
                target_kind="alien",
                target_id="x",
            )
        ]
    )

    processed = await worker.run_once(max_jobs=10)

    # Unknown target_kind still counts as processed — we drain the queue.
    assert processed == 1
    # A MachineEvent recording the skip is persisted for operator
    # observability; ``save_machine_event`` is called at least once (for the
    # processed event with ``skipped_unknown_target_kind``).
    fpg.save_machine_event.assert_awaited()
    last_call = fpg.save_machine_event.await_args.args[0]
    assert last_call.payload["decision_action"] == "skipped_unknown_target_kind"


async def test_memory_job_routes_to_memory_pipeline() -> None:
    memory = _pipeline_stub("memory_record")
    kb = _pipeline_stub("raw_document")
    worker, coord, _fpg = _make_worker(
        pipelines={"memory_record": memory, "raw_document": kb}
    )
    coord.dequeue_batch = AsyncMock(
        return_value=[
            FreshnessJob(
                workspace_id="ws",
                target_kind="memory_record",
                target_id="rec-1",
            )
        ]
    )

    await worker.run_once(max_jobs=10)

    memory.linker.run.assert_awaited_once_with("ws", "rec-1")
    memory.reconciler.run.assert_awaited_once_with("ws", "rec-1")
    memory.monitor.run.assert_awaited_once_with("ws", "rec-1")
    memory.curator.run.assert_awaited_once_with("ws", "rec-1")
    # KB pipeline stays untouched.
    kb.linker.run.assert_not_awaited()


async def test_kb_job_routes_to_kb_pipeline() -> None:
    memory = _pipeline_stub("memory_record")
    kb = _pipeline_stub("raw_document")
    worker, coord, _fpg = _make_worker(
        pipelines={"memory_record": memory, "raw_document": kb}
    )
    coord.dequeue_batch = AsyncMock(
        return_value=[
            FreshnessJob(
                workspace_id="ws",
                target_kind="raw_document",
                target_id="doc-1",
                event_type="content_changed",
            )
        ]
    )

    await worker.run_once(max_jobs=10)

    kb.linker.run.assert_awaited_once_with("ws", "doc-1")
    kb.reconciler.run.assert_awaited_once_with("ws", "doc-1")
    kb.monitor.run.assert_awaited_once_with("ws", "doc-1")
    kb.curator.run.assert_awaited_once_with("ws", "doc-1")
    # Memory pipeline stays untouched.
    memory.linker.run.assert_not_awaited()


async def test_knowledge_deleted_short_circuits_without_stages() -> None:
    memory = _pipeline_stub("memory_record")
    worker, coord, _fpg = _make_worker(pipelines={"memory_record": memory})
    coord.dequeue_batch = AsyncMock(
        return_value=[
            FreshnessJob(
                workspace_id="ws",
                target_kind="memory_record",
                target_id="rec-1",
                event_type="knowledge_deleted",
            )
        ]
    )

    processed = await worker.run_once(max_jobs=10)

    assert processed == 1
    memory.linker.run.assert_not_awaited()
    memory.reconciler.run.assert_not_awaited()
