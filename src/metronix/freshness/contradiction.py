"""Tell a contradiction from a duplicate among near-identical records (#516).

The Reconciler flags a pair as ``possible_duplicate`` when their cosine similarity
passes a gate. Embeddings encode topic, not truth value, so a record that
contradicts an older one ("the limit is 100/min" vs "the limit is 1000/min")
passes that gate as easily as a paraphrase. The scorers here run only on the pairs
that already passed the gate:

``nli``      small NLI cross-encoder, ~25-40 ms per pair on CPU, no LLM call. It
             catches updates but also calls two facts about *different* subjects
             with the same predicate a contradiction ("Denmark is in Europe" vs
             "Sweden is in Europe"), a known artifact of NLI training data.
``llm``      the freshness SLM answers yes/no per pair (~0.8 s for qwen2.5:3b on
             CPU); precise, and cheap next to graph extraction because the gate
             lets through well under one pair per record.
``nli+llm``  the SLM only on the pairs NLI flags.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from metronix.llm.base import LLMProvider

logger = structlog.get_logger()

SCORER_MODES = ("nli", "llm", "nli+llm")
JUDGE_PROMPT = (
    "Two statements from an agent's memory:\n"
    "A: {a}\nB: {b}\n\n"
    "Do A and B contradict each other, i.e. can they not both be true at the same "
    "time? Answer with one word: yes or no."
)
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


class LlmContradictionScorer:
    """Yes/no judgement per pair from an LLM provider: 1.0 for yes, 0.0 otherwise."""

    def __init__(self, provider: LLMProvider, max_chars: int = 1000) -> None:
        self._provider = provider
        self._max_chars = max_chars

    def contradiction_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        from metronix.llm.base import Message

        cut = self._max_chars
        scores = []
        for a, b in pairs:
            prompt = JUDGE_PROMPT.format(a=a[:cut], b=b[:cut])
            response = self._provider.chat_completion(
                messages=[Message(role="user", content=prompt)],
                temperature=0.0,
                max_tokens=3,
            )
            scores.append(1.0 if response.content.strip().lower().startswith("yes") else 0.0)
        return scores


class CascadeContradictionScorer:
    """``second`` only on the pairs ``first`` scores at or above ``threshold``."""

    def __init__(
        self, first: ContradictionScorer, second: ContradictionScorer, threshold: float = 0.5
    ) -> None:
        self._first = first
        self._second = second
        self._threshold = threshold

    def contradiction_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores = list(self._first.contradiction_scores(pairs))
        flagged = [i for i, score in enumerate(scores) if score >= self._threshold]
        if flagged:
            second = self._second.contradiction_scores([pairs[i] for i in flagged])
            for i, score in zip(flagged, second, strict=True):
                scores[i] = score
        return scores


def build_contradiction_scorer(
    mode: str,
    nli_model: str = DEFAULT_NLI_MODEL,
    provider: LLMProvider | None = None,
) -> ContradictionScorer:
    """Scorer for ``mode``; the LLM modes fall back to ``nli`` without a provider."""
    if mode not in SCORER_MODES:
        raise ValueError(f"unknown contradiction scorer {mode!r}; expected one of {SCORER_MODES}")
    nli = get_nli_scorer(nli_model)
    if mode == "nli":
        return nli
    if provider is None:
        logger.warning("freshness.contradiction.no_llm_provider", mode=mode, fallback="nli")
        return nli
    judge = LlmContradictionScorer(provider)
    return judge if mode == "llm" else CascadeContradictionScorer(nli, judge)
