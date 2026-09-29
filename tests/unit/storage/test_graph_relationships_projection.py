"""Regression tests for issue #508: relationship queries must project endpoint names.

A bare ``RETURN r`` yields a Relationship whose start/end nodes have no
properties, so every source/target name came back as "" and recall_graph's
BFS never expanded past its seeds.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _rel_row(source: str, target: str, rtype: str = "RELATED_TO") -> dict:
    return {
        "source": source,
        "target": target,
        "type": rtype,
        "valid_from": "2025-01-01",
        "valid_to": None,
    }


def _mock_driver(outgoing: list[dict], incoming: list[dict]):
    """Driver whose session answers outgoing (->) and incoming (<-) queries separately."""

    def _run(query: str, params: dict):
        if "(e:Entity)-[r]->(b:Entity)" in query:
            return outgoing
        if "(e:Entity)<-[r]-(b:Entity)" in query:
            return incoming
        return []

    session = MagicMock()
    session.run.side_effect = _run
    drv = MagicMock()
    drv.session.return_value.__enter__ = MagicMock(return_value=session)
    drv.session.return_value.__exit__ = MagicMock(return_value=False)
    return drv, session


@pytest.mark.parametrize("workspace_id", [None, "ws1"])
@patch("metronix.storage.graph_ops.get_graph_driver")
def test_graph_relationships_projects_names(mock_get_driver: MagicMock, workspace_id) -> None:
    drv, session = _mock_driver(
        outgoing=[_rel_row("Alice", "Acme", "WORKS_AT")],
        incoming=[_rel_row("Bob", "Alice", "MANAGES")],
    )
    mock_get_driver.return_value = drv

    from metronix.storage.graph_ops import get_graph_relationships

    rels = get_graph_relationships(["Alice"], workspace_id=workspace_id)

    assert rels == [
        {
            "source": "Alice",
            "target": "Acme",
            "type": "WORKS_AT",
            "valid_from": "2025-01-01",
            "valid_to": None,
        },
        {
            "source": "Bob",
            "target": "Alice",
            "type": "MANAGES",
            "valid_from": "2025-01-01",
            "valid_to": None,
        },
    ]
    for call in session.run.call_args_list:
        query = call[0][0]
        assert not query.rstrip().endswith("RETURN r")
        assert "e.name AS" in query and "b.name AS" in query


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_incoming_query_puts_neighbour_first(mock_get_driver: MagicMock) -> None:
    drv, session = _mock_driver(outgoing=[], incoming=[])
    mock_get_driver.return_value = drv

    from metronix.storage.graph_ops import get_graph_relationships

    get_graph_relationships(["Alice"], workspace_id="ws1")

    queries = [call[0][0] for call in session.run.call_args_list]
    out_q = next(q for q in queries if "-[r]->" in q)
    in_q = next(q for q in queries if "<-[r]-" in q)
    assert "RETURN e.name AS source, b.name AS target" in out_q
    assert "RETURN b.name AS source, e.name AS target" in in_q


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_relationships_at_date_projects_names(mock_get_driver: MagicMock) -> None:
    drv, _ = _mock_driver(outgoing=[_rel_row("Alice", "Acme")], incoming=[])
    mock_get_driver.return_value = drv

    from metronix.storage.graph_ops import get_relationships_at_date

    rels = get_relationships_at_date(["Alice"], target_date="2025-06-15", workspace_id="ws1")

    assert [(r["source"], r["target"]) for r in rels] == [("Alice", "Acme")]


@patch("metronix.retrieval.channels.get_hybrid_store")
@patch("metronix.retrieval.channels.get_doc_labels_by_entities")
@patch("metronix.retrieval.channels.resolve_entity_aliases_batch", return_value={})
@patch("metronix.storage.graph_ops.get_graph_driver")
def test_recall_graph_bfs_reaches_hop1(
    mock_get_driver: MagicMock,
    _aliases: MagicMock,
    mock_doc_labels: MagicMock,
    mock_store: MagicMock,
) -> None:
    """End-to-end over mocks: seed -> neighbour via projected names -> neighbour's doc."""
    drv, _ = _mock_driver(outgoing=[_rel_row("Seed Entity", "Bridge Entity")], incoming=[])
    mock_get_driver.return_value = drv

    labels = {"Seed Entity": "doc:p1", "Bridge Entity": "doc:p2"}
    mock_doc_labels.side_effect = lambda names, workspace_id=None: [
        {"doc_label": labels[n], "title": n} for n in names if n in labels
    ]
    store = MagicMock()
    store.search_by_doc_labels.side_effect = lambda dls, limit: [
        {"id": dl, "doc_label": dl, "text": dl, "score": 1.0} for dl in sorted(dls)
    ]
    mock_store.return_value = store

    from metronix.retrieval.channels import RecallContext, recall_graph

    settings = MagicMock()
    settings.recall_top_n_graph = 5
    settings.recall_graph_max_depth = 2
    settings.retrieval_graph_ner_enabled = True
    ctx = RecallContext(
        original_query="q",
        translated_query="q",
        expanded_query="q",
        detected_language="en",
        workspace_id="ws1",
        access_filter=None,
        settings=settings,
        extracted_jira_keys=[],
        extracted_title_entities=["Seed Entity"],
        extracted_dates=None,
        detected_person=[],
        is_activity_query=False,
    )

    results = recall_graph(ctx)

    assert {r["doc_label"] for r in results} == {"doc:p1", "doc:p2"}
