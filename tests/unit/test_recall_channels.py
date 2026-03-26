from unittest.mock import MagicMock

from metatron.retrieval.channels import RecallContext, ScoredResult, merge_channels


def _make_ctx(**overrides) -> RecallContext:
    """Helper to build RecallContext with sensible defaults."""
    defaults = {
        "original_query": "test query",
        "translated_query": "test query",
        "expanded_query": "test query expanded",
        "detected_language": "en",
        "workspace_id": "TEST",
        "access_filter": None,
        "settings": MagicMock(recall_top_n_dense=30, recall_top_n_exact=10, recall_top_n_metadata=10, recall_top_n_graph=5),
        "extracted_jira_keys": [],
        "extracted_title_entities": [],
        "extracted_dates": None,
        "detected_person": [],
        "is_activity_query": False,
    }
    defaults.update(overrides)
    return RecallContext(**defaults)


def test_recall_context_creation():
    ctx = _make_ctx(
        original_query="What is MTRNIX-104?",
        extracted_jira_keys=["MTRNIX-104"],
    )
    assert ctx.original_query == "What is MTRNIX-104?"
    assert ctx.extracted_jira_keys == ["MTRNIX-104"]
    assert ctx.is_activity_query is False
    assert ctx.detected_person == []


def test_scored_result_is_typed_dict():
    result: ScoredResult = {
        "chunk_id": "abc-123",
        "doc_label": "MTRNIX-104",
        "score": 0.85,
        "memory": {"title": "RBAC impl", "text": "...", "type": "jira"},
    }
    assert result["chunk_id"] == "abc-123"
    assert result["doc_label"] == "MTRNIX-104"
    assert result["score"] == 0.85


def test_merge_deduplicates_by_chunk_id():
    """Same chunk from two channels — keep max score."""
    ch1 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.8, "memory": {}}]
    ch2 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.9, "memory": {}}]
    merged = merge_channels([ch1, ch2])
    assert len(merged) == 1
    assert merged[0]["score"] == 0.9


def test_merge_preserves_multiple_chunks_same_doc():
    """Different chunks from same doc — both kept."""
    ch1 = [{"chunk_id": "a", "doc_label": "DOC-1", "score": 0.8, "memory": {}}]
    ch2 = [{"chunk_id": "b", "doc_label": "DOC-1", "score": 0.7, "memory": {}}]
    merged = merge_channels([ch1, ch2])
    assert len(merged) == 2


def test_merge_sorts_by_score_descending():
    ch1 = [{"chunk_id": "a", "doc_label": "D1", "score": 0.5, "memory": {}}]
    ch2 = [{"chunk_id": "b", "doc_label": "D2", "score": 0.9, "memory": {}}]
    ch3 = [{"chunk_id": "c", "doc_label": "D3", "score": 0.7, "memory": {}}]
    merged = merge_channels([ch1, ch2, ch3])
    scores = [r["score"] for r in merged]
    assert scores == [0.9, 0.7, 0.5]


def test_merge_handles_empty_channels():
    ch1 = [{"chunk_id": "a", "doc_label": "D1", "score": 0.8, "memory": {}}]
    merged = merge_channels([ch1, [], [], []])
    assert len(merged) == 1


def test_merge_all_empty():
    merged = merge_channels([[], [], [], []])
    assert merged == []
