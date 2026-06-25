"""GraphSweeper: periodic batch graph extraction for unsynced raw_documents.

MCP-stored documents (and any other ingest that defers graph extraction) land
in raw_documents with graph_synced=false. The sweeper is the durable, bounded,
single-flight consumer of that backlog: one loop, processing each affected
workspace in turn via process_all_unsynced_graphs.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import metronix.ingestion.pipeline as pipeline_mod
from metronix.api.graph_sweep import GraphSweeper


class _Store:
    def __init__(self, workspaces: list[str]) -> None:
        self._workspaces = workspaces

    async def list_workspaces_with_unsynced_graphs(self) -> list[str]:
        return self._workspaces


async def test_tick_processes_each_unsynced_workspace_throttled(monkeypatch):
    processed: list[str] = []
    rounds_seen: list[int] = []

    async def _fake_process(workspace_id, store, max_rounds=10, recovery_delay=30):
        processed.append(workspace_id)
        rounds_seen.append(max_rounds)
        return {"ok": 1, "errors": 0, "rounds": 1}

    monkeypatch.setattr(pipeline_mod, "process_all_unsynced_graphs", _fake_process)

    sweeper = GraphSweeper(_Store(["WS1", "WS2"]), MagicMock())
    await sweeper.tick()

    assert processed == ["WS1", "WS2"]
    # Throttled: at most one batch per workspace per tick.
    assert rounds_seen == [1, 1]


async def test_tick_noop_when_no_unsynced_workspaces(monkeypatch):
    called = {"n": 0}

    async def _fake_process(workspace_id, store, max_rounds=10, recovery_delay=30):
        called["n"] += 1
        return {"ok": 0, "errors": 0}

    monkeypatch.setattr(pipeline_mod, "process_all_unsynced_graphs", _fake_process)

    sweeper = GraphSweeper(_Store([]), MagicMock())
    await sweeper.tick()

    assert called["n"] == 0


async def test_tick_continues_past_a_failing_workspace(monkeypatch):
    processed: list[str] = []

    async def _fake_process(workspace_id, store, max_rounds=10, recovery_delay=30):
        processed.append(workspace_id)
        if workspace_id == "WS1":
            raise RuntimeError("neo4j down")
        return {"ok": 1, "errors": 0}

    monkeypatch.setattr(pipeline_mod, "process_all_unsynced_graphs", _fake_process)

    sweeper = GraphSweeper(_Store(["WS1", "WS2"]), MagicMock())
    # A single failing workspace must not abort the tick.
    await sweeper.tick()

    assert processed == ["WS1", "WS2"]
