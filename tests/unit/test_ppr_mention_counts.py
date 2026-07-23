from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from metronix.storage.graph_jira import _write_jira_entities
from metronix.storage.neo4j_graph import extract_graph_from_text, write_doc_graph


@patch("metronix.storage.neo4j_graph.chat_completion")
def test_extraction_preserves_normalized_mention_frequency(mock_completion: MagicMock) -> None:
    mock_completion.return_value = json.dumps(
        {
            "entities": [
                {"name": "Qdrant", "type": "database"},
                {"name": "Qdrant", "type": "database"},
            ],
            "relationships": [],
        }
    )

    graph = extract_graph_from_text("Qdrant is mentioned twice")

    assert graph["entities"] == [{"name": "Qdrant", "type": "Technology"}]
    assert graph["mention_counts"] == {"Qdrant": 2}


@patch("metronix.storage.neo4j_graph.get_graph_driver")
@patch("metronix.storage.neo4j_graph.extract_graph_from_text")
def test_document_writer_persists_mention_count(
    mock_extract: MagicMock, mock_driver: MagicMock
) -> None:
    mock_extract.return_value = {
        "entities": [{"name": "Qdrant", "type": "Technology"}],
        "relationships": [],
        "mention_counts": {"Qdrant": 2},
    }
    session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = session

    write_doc_graph("text", "guide.md", "user-1", "workspace-a", doc_label="DOC-1")

    mention_calls = [call for call in session.run.call_args_list if "MENTIONS" in call.args[0]]
    assert mention_calls[0].args[1]["mention_count"] == 2


def test_jira_writer_persists_mention_count() -> None:
    session = MagicMock()
    _write_jira_entities(
        session,
        {
            "entities": [{"name": "Qdrant", "type": "Technology"}],
            "relationships": [],
            "mention_counts": {"Qdrant": 2},
        },
        "PROJ-1",
        "workspace-a",
        "user-1",
        "PROJ-1",
    )

    mention_calls = [call for call in session.run.call_args_list if "MENTIONS" in call.args[0]]
    assert mention_calls[0].args[1]["mention_count"] == 2


@patch("metronix.storage.neo4j_graph.get_graph_driver")
@patch("metronix.storage.neo4j_graph.extract_graph_from_text")
def test_legacy_graph_payload_defaults_mention_count_to_one(
    mock_extract: MagicMock, mock_driver: MagicMock
) -> None:
    mock_extract.return_value = {
        "entities": [{"name": "Qdrant", "type": "Technology"}],
        "relationships": [],
    }
    session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = session

    write_doc_graph("text", "guide.md", "user-1", "workspace-a", doc_label="DOC-1")

    mention_calls = [call for call in session.run.call_args_list if "MENTIONS" in call.args[0]]
    assert mention_calls[0].args[1]["mention_count"] == 1
