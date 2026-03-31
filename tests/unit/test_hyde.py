"""Tests for HyDE (Hypothetical Document Embedding) feature."""

from unittest.mock import MagicMock, patch

from metatron.retrieval.channels import RecallContext
from metatron.retrieval.query_expansion import (
    generate_hypothetical_document,
    get_hyde_embedding,
)


def _make_settings(**overrides):
    s = MagicMock()
    s.hyde_enabled = True
    s.hyde_max_words = 4
    s.hyde_timeout = 8
    s.query_classifier_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_generate_hypothetical_document():
    """Mock LLM, verify returns text."""
    with patch("metatron.retrieval.query_expansion.chat_completion") as mock_llm:
        mock_llm.return_value = "Metatron is an enterprise knowledge management platform."
        result = generate_hypothetical_document("What is Metatron?")
        assert result == "Metatron is an enterprise knowledge management platform."
        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args
        assert call_kwargs.kwargs["temperature"] == 0.3
        assert call_kwargs.kwargs["max_tokens"] == 200


def test_generate_hypothetical_document_failure():
    """Mock LLM error, verify returns None."""
    with patch("metatron.retrieval.query_expansion.chat_completion") as mock_llm:
        mock_llm.side_effect = RuntimeError("LLM unavailable")
        result = generate_hypothetical_document("What is Metatron?")
        assert result is None


def test_get_hyde_embedding():
    """Mock LLM + embedding, verify returns vector."""
    settings = _make_settings()
    with (
        patch("metatron.retrieval.query_expansion.chat_completion") as mock_llm,
        patch("metatron.llm.embeddings.get_cached_embedding") as mock_embed,
    ):
        mock_llm.return_value = "Metatron is an enterprise platform."
        mock_embed.return_value = [0.1] * 768
        result = get_hyde_embedding("What is Metatron?", settings)
        assert result is not None
        assert len(result) == 768
        mock_embed.assert_called_once_with("Metatron is an enterprise platform.")


def test_hyde_detection_short_query():
    """2-word query + mixed profile -> triggers HyDE."""
    query = "deployment status"
    settings = _make_settings()
    classification = {"profile": "mixed", "confidence": 0.8, "method": "rule"}
    word_count = len(query.split())
    is_vague = word_count <= settings.hyde_max_words and classification["profile"] in (
        "mixed",
        "documentation",
    )
    assert is_vague is True


def test_hyde_detection_long_query():
    """10-word query -> skips HyDE."""
    query = "what is the current status of the deployment pipeline for metatron"
    settings = _make_settings()
    classification = {"profile": "mixed", "confidence": 0.8, "method": "rule"}
    word_count = len(query.split())
    is_vague = word_count <= settings.hyde_max_words and classification["profile"] in (
        "mixed",
        "documentation",
    )
    assert is_vague is False


def test_hyde_detection_execution_profile():
    """Short query + execution profile -> skips HyDE."""
    query = "MTRNIX-215"
    settings = _make_settings()
    classification = {"profile": "execution", "confidence": 0.9, "method": "rule"}
    word_count = len(query.split())
    is_vague = word_count <= settings.hyde_max_words and classification["profile"] in (
        "mixed",
        "documentation",
    )
    assert is_vague is False


def test_recall_dense_uses_hyde_embedding():
    """Mock store, verify dense_search_raw called with HyDE vector."""
    mock_store = MagicMock()
    mock_point = MagicMock()
    mock_point.id = "point-1"
    mock_point.payload = {
        "data": "some text",
        "title": "Doc",
        "type": "confluence",
        "url": "http://example.com",
        "date": "2025-01-01",
        "doc_label": "confluence:123",
        "workspace_id": "TEST",
    }
    mock_store.dense_search_raw.return_value = [("point-1", 0.95)]
    mock_store.client.retrieve.return_value = [mock_point]
    mock_store._format_result.return_value = {
        "id": "point-1",
        "score": 0.95,
        "memory": "some text",
        "data": "some text",
        "title": "Doc",
        "type": "confluence",
        "url": "http://example.com",
        "date": "2025-01-01",
        "doc_label": "confluence:123",
        "workspace_id": "TEST",
        "payload": mock_point.payload,
    }

    hyde_vec = [0.1] * 768
    ctx = RecallContext(
        original_query="test",
        translated_query="test",
        expanded_query="test",
        detected_language="en",
        workspace_id="TEST",
        access_filter=None,
        settings=MagicMock(
            recall_top_n_dense=30,
            adaptive_rrf_enabled=False,
        ),
        extracted_jira_keys=[],
        extracted_title_entities=[],
        extracted_dates=None,
        detected_person=[],
        is_activity_query=False,
        hyde_embedding=hyde_vec,
    )

    with patch(
        "metatron.retrieval.channels.get_hybrid_store",
        return_value=mock_store,
    ):
        from metatron.retrieval.channels import recall_dense

        results = recall_dense(ctx)

    mock_store.dense_search_raw.assert_called_once_with(
        hyde_vec,
        limit=90,
        filter_conditions=None,
    )
    mock_store.client.retrieve.assert_called_once()
    assert len(results) == 1
    assert results[0]["channel"] == "dense"
