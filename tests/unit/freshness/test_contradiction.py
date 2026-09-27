"""NLI contradiction scorer (#516): both reading orders, label lookup, lazy load."""

from __future__ import annotations

import sys
import types

import pytest

from metronix.freshness import contradiction


class _FakeCrossEncoder:
    loads = 0

    def __init__(self, name: str, device: str = "cpu") -> None:
        type(self).loads += 1
        self.model = types.SimpleNamespace(
            config=types.SimpleNamespace(
                id2label={0: "contradiction", 1: "entailment", 2: "neutral"}
            )
        )

    def predict(self, pairs, apply_softmax: bool = False):
        # Contradiction probability encoded in the first text: "c=<p>" when read
        # first, 0.1 otherwise.
        out = []
        for a, _ in pairs:
            p = float(a.split("c=")[1]) if a.startswith("c=") else 0.1
            out.append([p, (1 - p) / 2, (1 - p) / 2])
        return out


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    _FakeCrossEncoder.loads = 0
    module = types.ModuleType("sentence_transformers")
    module.CrossEncoder = _FakeCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return _FakeCrossEncoder


def test_scores_take_the_larger_direction(fake_sentence_transformers) -> None:
    scorer = contradiction.NliContradictionScorer("fake")
    scores = scorer.contradiction_scores([("c=0.9", "x"), ("y", "c=0.7"), ("a", "b")])
    assert scores == pytest.approx([0.9, 0.7, 0.1])


def test_model_is_loaded_once_and_not_for_empty_input(fake_sentence_transformers) -> None:
    scorer = contradiction.NliContradictionScorer("fake")
    assert scorer.contradiction_scores([]) == []
    assert fake_sentence_transformers.loads == 0
    scorer.contradiction_scores([("a", "b")])
    scorer.contradiction_scores([("a", "b")])
    assert fake_sentence_transformers.loads == 1


def test_model_without_contradiction_label_is_rejected(monkeypatch) -> None:
    class _NoLabel(_FakeCrossEncoder):
        def __init__(self, name: str, device: str = "cpu") -> None:
            super().__init__(name, device)
            self.model.config.id2label = {0: "LABEL_0", 1: "LABEL_1"}

    module = types.ModuleType("sentence_transformers")
    module.CrossEncoder = _NoLabel
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    with pytest.raises(ValueError, match="contradiction"):
        contradiction.NliContradictionScorer("fake").contradiction_scores([("a", "b")])


def test_get_nli_scorer_is_shared_per_model() -> None:
    first = contradiction.get_nli_scorer("model-a")
    assert contradiction.get_nli_scorer("model-a") is first
    assert contradiction.get_nli_scorer("model-b") is not first


class _Provider:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    def chat_completion(self, messages, temperature, max_tokens):
        prompt = messages[0].content
        self.prompts.append(prompt)
        answer = next((a for key, a in self.answers.items() if key in prompt), "no")
        return types.SimpleNamespace(content=answer)


class _Fixed:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[list[tuple[str, str]]] = []

    def contradiction_scores(self, pairs):
        self.calls.append(pairs)
        return self.scores[: len(pairs)]


def test_llm_scorer_reads_yes_as_contradiction() -> None:
    provider = _Provider({"limit is 1000": " Yes.", "Sweden": "No"})
    scorer = contradiction.LlmContradictionScorer(provider)
    pairs = [("limit is 100", "limit is 1000"), ("Denmark is in Europe", "Sweden is in Europe")]
    assert scorer.contradiction_scores(pairs) == [1.0, 0.0]
    assert "A: limit is 100\nB: limit is 1000" in provider.prompts[0]


def test_cascade_asks_the_judge_only_about_flagged_pairs() -> None:
    first = _Fixed([0.9, 0.1, 0.8])
    second = _Fixed([0.0, 1.0])
    cascade = contradiction.CascadeContradictionScorer(first, second, threshold=0.5)
    assert cascade.contradiction_scores([("a", "1"), ("b", "2"), ("c", "3")]) == [0.0, 0.1, 1.0]
    assert second.calls == [[("a", "1"), ("c", "3")]]


def test_builder_modes_and_fallback() -> None:
    provider = _Provider({})
    assert isinstance(
        contradiction.build_contradiction_scorer("nli", "m"), contradiction.NliContradictionScorer
    )
    assert isinstance(
        contradiction.build_contradiction_scorer("llm", "m", provider),
        contradiction.LlmContradictionScorer,
    )
    assert isinstance(
        contradiction.build_contradiction_scorer("nli+llm", "m", provider),
        contradiction.CascadeContradictionScorer,
    )
    # Without an SLM the LLM modes degrade to NLI instead of failing the worker.
    assert isinstance(
        contradiction.build_contradiction_scorer("nli+llm", "m", None),
        contradiction.NliContradictionScorer,
    )
    with pytest.raises(ValueError, match="unknown"):
        contradiction.build_contradiction_scorer("bert", "m")
