"""Tell a contradiction from a duplicate among near-identical records (#516).

The Reconciler flags a pair as ``possible_duplicate`` when their cosine similarity
passes a gate. Embeddings encode topic, not truth value, so a record that
contradicts an older one ("the limit is 100/min" vs "the limit is 1000/min")
passes that gate as easily as a paraphrase. A small NLI cross-encoder, run only on
the pairs that already passed the gate, separates the two without an LLM call.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()

DEFAULT_NLI_MODEL = "cross-encoder/nli-deberta-v3-xsmall"


@runtime_checkable
class ContradictionScorer(Protocol):
    """Scores how likely each pair of texts contradicts, in [0, 1]."""

    def contradiction_scores(self, pairs: list[tuple[str, str]]) -> list[float]: ...


class NliContradictionScorer:
    """NLI cross-encoder, both directions, lazily loaded once per process.

    The score of a pair is the larger contradiction probability of (a, b) and
    (b, a): an update often contradicts only in one reading order.
    """

    def __init__(self, model_name: str = DEFAULT_NLI_MODEL, max_chars: int = 1000) -> None:
        self._model_name = model_name
        self._max_chars = max_chars
        self._model = None
        self._contradiction_index: int | None = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from sentence_transformers import CrossEncoder

                model = CrossEncoder(self._model_name, device="cpu")
                labels = {
                    str(label).lower(): int(index)
                    for index, label in model.model.config.id2label.items()
                }
                if "contradiction" not in labels:
                    raise ValueError(f"{self._model_name} has no 'contradiction' label: {labels}")
                self._contradiction_index = labels["contradiction"]
                self._model = model
                logger.info("freshness.nli.loaded", model=self._model_name)
        return self._model

    def contradiction_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        model = self._load()
        cut = self._max_chars
        both = [(a[:cut], b[:cut]) for a, b in pairs] + [(b[:cut], a[:cut]) for a, b in pairs]
        probs = model.predict(both, apply_softmax=True)
        index = self._contradiction_index
        n = len(pairs)
        return [max(float(probs[i][index]), float(probs[n + i][index])) for i in range(n)]


_default_scorer: NliContradictionScorer | None = None
_default_lock = threading.Lock()


def get_nli_scorer(model_name: str = DEFAULT_NLI_MODEL) -> NliContradictionScorer:
    """Process-wide scorer (the model is loaded on first use, not here)."""
    global _default_scorer
    with _default_lock:
        if _default_scorer is None or _default_scorer._model_name != model_name:
            _default_scorer = NliContradictionScorer(model_name)
        return _default_scorer
