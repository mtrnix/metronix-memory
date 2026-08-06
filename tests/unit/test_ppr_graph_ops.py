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
