"""get_memories_about_entity agent scoping (MTRNIX-372 P4)."""

import pytest

from metatron.core.models import MemoryRecord
from metatron.storage import memory_graph

pytestmark = pytest.mark.integration


def _save(ws: str, agent: str, rid: str, entity: str) -> None:
    rec = MemoryRecord(id=rid, workspace_id=ws, agent_id=agent, content="x")
    memory_graph.save_memory_to_graph(rec, entity_names=[entity])


def test_agent_scoped_filter() -> None:
    ws = "WS_ENT"
    _save(ws, "AG1", "r-a1", "Acme")
    _save(ws, "AG2", "r-a2", "Acme")
    all_rows = memory_graph.get_memories_about_entity(ws, "Acme")
    scoped = memory_graph.get_memories_about_entity(ws, "Acme", agent_id="AG1")
    all_ids = {r["id"] for r in all_rows}
    scoped_ids = {r["id"] for r in scoped}
    assert {"r-a1", "r-a2"}.issubset(all_ids)
    assert scoped_ids == {"r-a1"}
