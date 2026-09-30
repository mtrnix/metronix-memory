from __future__ import annotations

from unittest.mock import MagicMock, patch

from metronix.storage.graph_ops import get_doc_labels_by_entities


def _node(**props: object) -> MagicMock:
    node = MagicMock()
    node.get.side_effect = lambda key, default=None: props.get(key, default)
    return node


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_titles_are_fetched_in_one_labelled_query(mock_get_driver: MagicMock) -> None:
    session = MagicMock()
    title_queries: list[str] = []

    def run(query: str, params: dict) -> list:
        if "RETURN e" in query:  # path 1: Entity.doc_labels
            return [(_node(doc_labels=["DOC-1", "DOC-2"]),)]
        if "[:MENTIONS]" in query:  # path 2: MENTIONS edges
            return [(_node(doc_label="DOC-3"),)]
        title_queries.append(query)
        assert sorted(params["dls"]) == ["DOC-1", "DOC-2", "DOC-3"]
        return [
            (_node(doc_label="DOC-1", file_name="one.md"),),
            (_node(doc_label="DOC-3", issue_key="PROJ-3"),),
        ]

    session.run.side_effect = run
    mock_get_driver.return_value.session.return_value.__enter__.return_value = session

    results = get_doc_labels_by_entities(["Entity"], "ws")

    assert len(title_queries) == 1
    assert "MATCH (d:Document)" in title_queries[0]
    assert "MATCH (d:JiraIssue)" in title_queries[0]
    # DOC-2 has no node: dropped, as before.
    assert sorted(results, key=lambda r: r["doc_label"]) == [
        {"doc_label": "DOC-1", "title": "one.md"},
        {"doc_label": "DOC-3", "title": "PROJ-3"},
    ]


@patch("metronix.storage.graph_ops.get_graph_driver")
def test_no_title_query_without_labels(mock_get_driver: MagicMock) -> None:
    session = MagicMock()
    session.run.return_value = []
    mock_get_driver.return_value.session.return_value.__enter__.return_value = session

    assert get_doc_labels_by_entities(["Nothing"], "ws") == []
    assert all("doc_label IN $dls" not in call.args[0] for call in session.run.call_args_list)
