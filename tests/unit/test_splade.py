"""Tests for SPLADE sparse vector computation and dispatch logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import torch


@pytest.fixture()
def _mock_splade_model():
    """Mock _get_splade_model to return a fake model + tokenizer."""
    import metatron.ingestion.splade as splade_mod

    # Reset global singleton state
    splade_mod._model = None
    splade_mod._tokenizer = None

    # Build a fake model that returns controlled logits
    vocab_size = 200
    mock_tokenizer = MagicMock()
    mock_tokenizer.return_value = {
        "input_ids": torch.ones(1, 5, dtype=torch.long),
        "attention_mask": torch.ones(1, 5, dtype=torch.long),
    }

    mock_model = MagicMock()
    # Simulate logits: (1, seq_len=5, vocab_size=200)
    # Set specific positions to have positive values after ReLU
    fake_logits = torch.zeros(1, 5, vocab_size)
    fake_logits[0, 0, 10] = 2.0
    fake_logits[0, 1, 42] = 3.0
    fake_logits[0, 2, 100] = 1.0
    mock_output = MagicMock()
    mock_output.logits = fake_logits
    mock_model.return_value = mock_output
    mock_model.parameters.return_value = iter([torch.nn.Parameter(torch.zeros(1))])

    with patch.object(splade_mod, "_get_splade_model", return_value=(mock_model, mock_tokenizer)):
        yield {
            "model": mock_model,
            "tokenizer": mock_tokenizer,
        }

    # Clean up singleton
    splade_mod._model = None
    splade_mod._tokenizer = None


class TestSpladeComputation:
    """Test SPLADE sparse vector computation."""

    def test_compute_splade_sparse_vector(self, _mock_splade_model):
        """Mock model output produces correct (indices, values) tuple."""
        from metatron.ingestion.splade import compute_splade_sparse_vector

        indices, values = compute_splade_sparse_vector("test document text")
        assert isinstance(indices, list)
        assert isinstance(values, list)
        assert len(indices) == len(values)
        assert len(indices) > 0
        # Verify known non-zero positions
        assert 10 in indices
        assert 42 in indices
        assert 100 in indices
        # Values should be log1p of the logit values
        for v in values:
            assert v > 0.0

    def test_compute_splade_query_vector(self, _mock_splade_model):
        """Query vector uses shorter max_length but same model."""
        from metatron.ingestion.splade import compute_splade_query_vector

        indices, values = compute_splade_query_vector("test query")
        assert isinstance(indices, list)
        assert isinstance(values, list)
        assert len(indices) == len(values)
        assert len(indices) > 0

    def test_lazy_model_loading(self):
        """Model is loaded only on first call, not on import."""
        import metatron.ingestion.splade as splade_mod

        splade_mod._model = None
        splade_mod._tokenizer = None

        # Before any call, model should be None
        assert splade_mod._model is None

        fake_param = torch.nn.Parameter(torch.zeros(1))
        fake_model = MagicMock()
        fake_model.parameters.side_effect = lambda: iter([fake_param])
        fake_tokenizer = MagicMock()

        with patch.object(
            splade_mod,
            "_get_splade_model",
            return_value=(fake_model, fake_tokenizer),
        ) as mock_get:
            fake_output = MagicMock()
            fake_output.logits = torch.zeros(1, 5, 100)
            fake_model.return_value = fake_output
            fake_tokenizer.return_value = {
                "input_ids": torch.ones(1, 5, dtype=torch.long),
                "attention_mask": torch.ones(1, 5, dtype=torch.long),
            }

            splade_mod.compute_splade_sparse_vector("first call")
            assert mock_get.call_count == 1

            splade_mod.compute_splade_sparse_vector("second call")
            assert mock_get.call_count == 2  # called each time (singleton is in _get)


class TestSpladeDispatch:
    """Test SPLADE/BM25 dispatch logic in qdrant.py."""

    def test_splade_disabled_uses_bm25(self, settings):
        """When splade_enabled=False, BM25 path is used."""
        settings.splade_enabled = False
        with patch("metatron.storage.qdrant.get_settings", return_value=settings):
            from metatron.storage.qdrant import _compute_doc_sparse, _compute_query_sparse

            with patch(
                "metatron.storage.qdrant.compute_bm25_sparse_vector",
                return_value=([1, 2], [0.5, 0.6]),
            ) as mock_bm25:
                result = _compute_doc_sparse("test text")
                mock_bm25.assert_called_once_with("test text")
                assert result == ([1, 2], [0.5, 0.6])

            with patch(
                "metatron.storage.qdrant.compute_query_sparse_vector",
                return_value=([3], [1.0]),
            ) as mock_bm25_q:
                result = _compute_query_sparse("test query")
                mock_bm25_q.assert_called_once_with("test query")
                assert result == ([3], [1.0])

    def test_splade_enabled_uses_splade(self, settings):
        """When splade_enabled=True, SPLADE path is used."""
        settings.splade_enabled = True
        with patch("metatron.storage.qdrant.get_settings", return_value=settings):
            from metatron.storage.qdrant import _compute_doc_sparse, _compute_query_sparse

            with patch(
                "metatron.ingestion.splade.compute_splade_sparse_vector",
                return_value=([10, 42], [0.5, 1.2]),
            ) as mock_splade:
                result = _compute_doc_sparse("test text")
                mock_splade.assert_called_once_with("test text")
                assert result == ([10, 42], [0.5, 1.2])

            with patch(
                "metatron.ingestion.splade.compute_splade_query_vector",
                return_value=([10], [0.8]),
            ) as mock_splade_q:
                result = _compute_query_sparse("test query")
                mock_splade_q.assert_called_once_with("test query")
                assert result == ([10], [0.8])
