from __future__ import annotations

from unittest.mock import MagicMock, patch

from metronix.storage.graph_ops import get_ppr_subgraph


def _record(
    left_id: str,
    left_label: str | None,
    left_labels: list[str],
    right_id: str,
    right_label: str | None,
    right_labels: list[str],
    relationship_type: str,
    mention_count: object,
) -> dict[str, object]:
    return {
        "left_id": left_id,
        "left_doc_label": left_label,
        "left_labels": left_labels,
        "right_id": right_id,
        "right_doc_label": right_label,
        "right_labels": right_labels,
        "relationship_type": relationship_type,
        "mention_count": mention_count,
    }


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_ppr_subgraph_scopes_nodes_and_uses_legacy_weight(mock_get_driver: MagicMock) -> None:
    session = MagicMock()
    session.run.return_value = [
        _record(
            "entity:auth",
            None,
            ["Entity"],
            "document:guide",
            "DOC-GUIDE",
            ["Document"],
            "MENTIONS",
            None,
        )
    ]
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    mock_get_driver.return_value = driver

    nodes, edges = get_ppr_subgraph(["Auth"], "workspace-a", max_nodes=10)

    query, params = session.run.call_args.args
    assert "seed.workspace_id = $ws" in query
    assert "left.workspace_id = $ws" in query
    assert "right.workspace_id = $ws" in query
    assert params["ws"] == "workspace-a"
    assert nodes == {"document:guide": "DOC-GUIDE", "entity:auth": None}
    assert edges == [("entity:auth", "document:guide", 1.0)]


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_ppr_subgraph_keeps_alias_and_weighted_mentions_only(mock_get_driver: MagicMock) -> None:
    session = MagicMock()
    session.run.return_value = [
        _record("entity:a", None, ["Entity"], "entity:b", None, ["Entity"], "ALIAS", 99),
        _record(
            "entity:b",
            None,
            ["Entity"],
            "jira:ticket",
            "PROJ-1",
            ["JiraIssue"],
            "MENTIONS",
            4,
        ),
        _record("entity:b", None, ["Entity"], "entity:c", None, ["Entity"], "RELATED_TO", 8),
    ]
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    mock_get_driver.return_value = driver

    nodes, edges = get_ppr_subgraph(["A"], "workspace-a", max_nodes=10)

    assert nodes["jira:ticket"] == "PROJ-1"
    assert edges == [("entity:a", "entity:b", 1.0), ("entity:b", "jira:ticket", 4.0)]


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_ppr_subgraph_limits_nodes_in_stable_order(mock_get_driver: MagicMock) -> None:
    session = MagicMock()
    session.run.return_value = [
        _record("entity:z", None, ["Entity"], "document:z", "DOC-Z", ["Document"], "MENTIONS", 1),
        _record("entity:a", None, ["Entity"], "document:a", "DOC-A", ["Document"], "MENTIONS", 1),
    ]
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    mock_get_driver.return_value = driver

    nodes, edges = get_ppr_subgraph(["A"], "workspace-a", max_nodes=2)

    assert nodes == {"document:a": "DOC-A", "entity:a": None}
    assert edges == [("entity:a", "document:a", 1.0)]


def _specific_session(seeds, seed_docs, doc_entities, aliases) -> MagicMock:
    """Session whose run() answers the four get_ppr_subgraph_specific queries."""

    def run(query, params):
        if "count(d) AS df" in query:
            return [s for s in seeds if s["name"] in params["names"]]
        if "RETURN elementId(e) AS eid, elementId(d) AS did" in query:
            return [r for r in seed_docs if r["eid"] in params["ids"]]
        if "m.mention_count" in query:
            return [r for r in doc_entities if r["did"] in params["ids"]]
        if ":ALIAS" in query:
            return [r for r in aliases if r["a"] in params["ids"] and r["b"] in params["ids"]]
        raise AssertionError(query)

    session = MagicMock()
    session.run.side_effect = run
    return session


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_specific_subgraph_takes_rare_seeds_first_and_skips_hubs(
    mock_get_driver: MagicMock,
) -> None:
    from metronix.storage.graph_ops import get_ppr_subgraph_specific

    session = _specific_session(
        seeds=[
            {"id": "e:rare", "name": "Rare", "df": 1},
            {"id": "e:mid", "name": "Mid", "df": 2},
            {"id": "e:hub", "name": "Hub", "df": 500},
        ],
        seed_docs=[
            {"eid": "e:rare", "did": "d:1", "doc_label": "DOC-1"},
            {"eid": "e:mid", "did": "d:2", "doc_label": "DOC-2"},
            {"eid": "e:mid", "did": "d:3", "doc_label": "DOC-3"},
            {"eid": "e:hub", "did": "d:9", "doc_label": "DOC-9"},
        ],
        doc_entities=[
            {"did": "d:1", "eid": "e:rare", "mention_count": 2},
            {"did": "d:1", "eid": "e:x", "mention_count": None},
            {"did": "d:2", "eid": "e:mid", "mention_count": 1},
            {"did": "d:3", "eid": "e:mid", "mention_count": 1},
        ],
        aliases=[{"a": "e:x", "b": "e:rare"}],
    )
    mock_get_driver.return_value.session.return_value.__enter__.return_value = session

    nodes, edges = get_ppr_subgraph_specific(
        ["Rare", "Mid", "Hub"], "workspace-a", max_docs=2, hub_cap=100
    )

    # Hub is above hub_cap; Rare's document comes first, then the first of Mid's.
    assert {n: label for n, label in nodes.items() if label} == {
        "d:1": "DOC-1",
        "d:2": "DOC-2",
    }
    assert {n for n, label in nodes.items() if label is None} == {"e:rare", "e:x", "e:mid"}
    assert ("d:1", "e:rare", 2.0) in edges
    assert ("d:1", "e:x", 1.0) in edges
    assert ("e:x", "e:rare", 1.0) in edges
    assert all("d:9" not in edge and "d:3" not in edge for edge in edges)


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_specific_subgraph_empty_without_specific_seeds(mock_get_driver: MagicMock) -> None:
    from metronix.storage.graph_ops import get_ppr_subgraph_specific

    session = _specific_session(
        seeds=[{"id": "e:hub", "name": "Hub", "df": 500}],
        seed_docs=[],
        doc_entities=[],
        aliases=[],
    )
    mock_get_driver.return_value.session.return_value.__enter__.return_value = session

    assert get_ppr_subgraph_specific(["Hub"], "workspace-a", hub_cap=100) == ({}, [])
    assert get_ppr_subgraph_specific([], "workspace-a") == ({}, [])
