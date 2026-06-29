"""SPLADE learned sparse representations for semantic search.

Replaces BM25 hash-based sparse vectors with learned term importance
weights from a Masked Language Model. Lazy singleton pattern (same as reranker).
"""

from __future__ import annotations

import threading

import structlog

logger = structlog.get_logger()

_model = None
_tokenizer = None
_lock = threading.Lock()


def _get_splade_model():
    """Lazy-load SPLADE model (thread-safe singleton)."""
    global _model, _tokenizer  # noqa: PLW0603
    if _model is None:
        with _lock:
            if _model is None:
                from metronix.core.config import get_settings

                s = get_settings()
                import torch  # noqa: TCH002
                from transformers import AutoModelForMaskedLM, AutoTokenizer

                _tokenizer = AutoTokenizer.from_pretrained(s.splade_model)
                _model = AutoModelForMaskedLM.from_pretrained(s.splade_model)
                _model.eval()
                if torch.cuda.is_available():
                    _model = _model.cuda()
                logger.info("splade.model.loaded", model=s.splade_model)
    return _model, _tokenizer


def compute_splade_sparse_vector(
    text: str,
    max_length: int = 256,
) -> tuple[list[int], list[float]]:
    """Compute SPLADE sparse vector for a document chunk."""
    import torch

    model, tokenizer = _get_splade_model()
    device = next(model.parameters()).device
    tokens = tokenizer(
        text,
        return_tensors="pt",
        max_length=max_length,
        truncation=True,
        padding=True,
    )
    tokens = {k: v.to(device) for k, v in tokens.items()}
    with torch.no_grad():
        output = model(**tokens)
    # SPLADE: log(1 + ReLU(logits)), max-pool over sequence length
    logits = output.logits  # (1, seq_len, vocab_size)
    splade_vector = torch.max(
        torch.log1p(torch.relu(logits)), dim=1
    ).values.squeeze()  # (vocab_size,)
    # Extract non-zero entries
    indices = splade_vector.nonzero(as_tuple=True)[0].tolist()
    values = splade_vector[indices].tolist()
    return indices, values


def compute_splade_query_vector(
    query: str,
    max_length: int = 64,
) -> tuple[list[int], list[float]]:
    """Compute SPLADE sparse vector for a query (shorter max_length)."""
    return compute_splade_sparse_vector(query, max_length=max_length)
