"""Wiring test: hybrid_search_and_answer populates and persists a RagTrace."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

from metatron.retrieval.trace import RagTrace

_SEARCH_MODULE = "metatron.retrieval.search"
_TID = UUID("22222222-2222-2222-2222-222222222222")


def _patch_search_internals():
    return {
        "merge_channels": patch(
            f"{_SEARCH_MODULE}.merge_channels",
            return_value=[
                {
                    "chunk_id": "c1",
                    "doc_label": "DOC-1",
                    "memory": {"id": "c1", "doc_label": "DOC-1", "text": "text one"},
                    "channels": ["dense"],
                    "channel_scores": {"dense": 0.9},
                }
            ],
        ),
        "chat_completion_with_retry": patch(
            f"{_SEARCH_MODULE}.chat_completion_with_retry",
            return_value="Test answer",
        ),
        "get_graph_entities": patch(f"{_SEARCH_MODULE}.get_graph_entities", return_value=[]),
        "get_entities_by_doc_labels": patch(
            f"{_SEARCH_MODULE}.get_entities_by_doc_labels", return_value=[]
        ),
        "get_graph_relationships": patch(
            f"{_SEARCH_MODULE}.get_graph_relationships", return_value=[]
        ),
        "get_doc_labels_by_entities": patch(
            f"{_SEARCH_MODULE}.get_doc_labels_by_entities", return_value=[]
        ),
        "expand_query": patch(
            f"{_SEARCH_MODULE}.expand_query", side_effect=lambda q: f"expanded {q}"
        ),
        "translate_query_to_english": patch(
            f"{_SEARCH_MODULE}.translate_query_to_english", side_effect=lambda q: q
        ),
        "select_fragments_within_budget": patch(
            f"{_SEARCH_MODULE}.select_fragments_within_budget",
            return_value=[
                {
                    "text": "fragment one",
                    "evidence_marker": "PRIMARY",
                    "title": "Doc One",
                    "doc_label": "DOC-1",
                    "date": "",
                }
            ],
        ),
        "estimate_graph_tokens": patch(f"{_SEARCH_MODULE}.estimate_graph_tokens", return_value=0),
        "truncate_graph_context": patch(
            f"{_SEARCH_MODULE}.truncate_graph_context", return_value=([], [], [])
        ),
        "detect_response_language": patch(
            f"{_SEARCH_MODULE}.detect_response_language", return_value="en"
        ),
        "should_use_team_workflow_schema": patch(
            f"{_SEARCH_MODULE}.should_use_team_workflow_schema", return_value=False
        ),
        "classify_query": patch(
            f"{_SEARCH_MODULE}.classify_query",
            return_value={"profile": "mixed", "confidence": 1.0, "method": "rule"},
        ),
        "recall_dense_async": patch(f"{_SEARCH_MODULE}.recall_dense_async", return_value=[]),
        "recall_exact_async": patch(f"{_SEARCH_MODULE}.recall_exact_async", return_value=[]),
        "recall_metadata_async": patch(f"{_SEARCH_MODULE}.recall_metadata_async", return_value=[]),
        "recall_graph_async": patch(f"{_SEARCH_MODULE}.recall_graph_async", return_value=[]),
    }


async def test_rag_trace_is_populated_and_persisted(monkeypatch):
    captured: dict = {}

    def _fake_store(trace: dict) -> None:
        captured.update(trace)

    monkeypatch.setattr(
        "metatron.storage.pg_connection.store_rag_trace_sync", _fake_store, raising=True
    )

    patches = _patch_search_internals()
    for p in patches.values():
        p.start()
    try:
        from metatron.retrieval.search import hybrid_search_and_answer

        trace = RagTrace(trace_id=_TID)
        trace.set_input(
            raw_user_message="What is Metatron?",
            history=[],
            composite_query="What is Metatron?",
        )
        answer = await hybrid_search_and_answer(
            query="What is Metatron?",
            workspace_id="ws_test",
            rag_trace=trace,
        )
    finally:
        for p in patches.values():
            p.stop()

    assert isinstance(answer, str)
    # Context fields filled by the pipeline (single source of truth)
    assert trace.source == "rest"
    assert trace.workspace_id == "ws_test"
    # All expected phase names present
    names = [p["name"] for p in trace.phases]
    for expected in (
        "resolve_query",
        "query_expansion",
        "translate_query",
        "classify",
        "recall",
        "merge_and_score",
        "rerank",
        "context_assembly",
        "generation",
    ):
        assert expected in names, f"missing phase {expected}"
    # Persisted dict reached the store with the right id
    assert captured.get("trace_id") == str(_TID)
    assert captured.get("total_ms", 0) >= 0


async def test_trace_persisted_on_llm_failure(monkeypatch):
    """If answer generation raises, the partial trace is still persisted with an
    error-marked generation phase (the failed-answer case is worth debugging too)."""
    captured: dict = {}
    monkeypatch.setattr(
        "metatron.storage.pg_connection.store_rag_trace_sync",
        lambda trace: captured.update(trace),
        raising=True,
    )

    patches = _patch_search_internals()

    def _boom(*args, **kwargs):
        raise RuntimeError("llm down")

    patches["chat_completion_with_retry"] = patch(
        f"{_SEARCH_MODULE}.chat_completion_with_retry", side_effect=_boom
    )
    for p in patches.values():
        p.start()
    try:
        from metatron.retrieval.search import hybrid_search_and_answer

        trace = RagTrace(trace_id=_TID)
        trace.set_input(raw_user_message="q", history=[], composite_query="q")
        answer = await hybrid_search_and_answer(query="q", workspace_id="ws_test", rag_trace=trace)
    finally:
        for p in patches.values():
            p.stop()

    assert "couldn't generate an answer" in answer
    # Persisted despite the failure, with an error-marked generation phase.
    assert captured.get("trace_id") == str(_TID)
    gen = [p for p in trace.phases if p["name"] == "generation"]
    assert gen and gen[-1].get("error") == "llm_answer_failed"


async def test_no_rag_trace_does_not_persist(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "metatron.storage.pg_connection.store_rag_trace_sync",
        lambda trace: calls.append(trace),
        raising=True,
    )
    patches = _patch_search_internals()
    for p in patches.values():
        p.start()
    try:
        from metatron.retrieval.search import hybrid_search_and_answer

        result = await hybrid_search_and_answer(
            query="Test", workspace_id="ws_test", return_trace=True
        )
    finally:
        for p in patches.values():
            p.stop()
    # Benchmarker path (rag_trace=None) must not persist a debug trace
    assert calls == []
    assert isinstance(result, dict)
