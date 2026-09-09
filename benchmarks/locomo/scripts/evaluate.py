"""Evaluate LoCoMo answers with the official category-specific token F1 rules."""

from __future__ import annotations

import argparse
import json
import re
import string
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks._shared import latency, retrieval_eval  # noqa: E402


def _stem(word: str) -> str:
    try:
        from nltk.stem import PorterStemmer
    except ImportError as exc:  # pragma: no cover - exercised by operator setup
        raise ImportError("Install LoCoMo requirements before evaluating") from exc
    return PorterStemmer().stem(word)


def normalize_answer(value: str) -> str:
    value = value.replace(",", "").lower()
    value = "".join(character for character in value if character not in string.punctuation)
    value = re.sub(r"\b(a|an|the|and)\b", " ", value)
    return " ".join(value.split())


def token_f1(prediction: str, ground_truth: str) -> float:
    prediction_tokens = [_stem(word) for word in normalize_answer(prediction).split()]
    truth_tokens = [_stem(word) for word in normalize_answer(ground_truth).split()]
    if not prediction_tokens or not truth_tokens:
        return float(prediction_tokens == truth_tokens)
    common = Counter(prediction_tokens) & Counter(truth_tokens)
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision = same / len(prediction_tokens)
    recall = same / len(truth_tokens)
    return 2 * precision * recall / (precision + recall)


def multi_answer_f1(prediction: str, ground_truth: str) -> float:
    predictions = [part.strip() for part in prediction.split(",")]
    truths = [part.strip() for part in ground_truth.split(",")]
    return sum(
        max(token_f1(candidate, truth) for candidate in predictions) for truth in truths
    ) / len(truths)


def score_answer(category: int, hypothesis: str, answer: str) -> float:
    if category == 5:
        lowered = hypothesis.lower()
        return float("no information available" in lowered or "not mentioned" in lowered)
    if category == 3:
        answer = answer.split(";", maxsplit=1)[0].strip()
    if category == 1:
        return multi_answer_f1(hypothesis, answer)
    if category in {2, 3, 4}:
        return token_f1(hypothesis, answer)
    raise ValueError(f"unsupported LoCoMo category: {category}")


def evaluate_rows(rows: list[dict]) -> dict[str, object]:
    if not rows:
        raise ValueError("results contain no LoCoMo questions")
    category_values: dict[int, list[float]] = defaultdict(list)
    error_count = 0
    scored_rows: list[dict] = []
    for row in rows:
        category = int(row["category"])
        hypothesis = str(row["hypothesis"])
        answer = str(row.get("answer", ""))
        score = score_answer(category, hypothesis, answer)
        error_count += hypothesis.startswith("Error:")
        category_values[category].append(score)
        scored_rows.append(
            {"question_id": row.get("question_id"), "category": category, "score": score}
        )
    all_scores = [item["score"] for item in scored_rows]
    return {
        "schema_version": 2,
        "question_count": len(rows),
        "error_count": error_count,
        "overall_score": sum(all_scores) / len(all_scores),
        "category_counts": {
            str(key): len(values) for key, values in sorted(category_values.items())
        },
        "category_scores": {
            str(key): sum(values) / len(values) for key, values in sorted(category_values.items())
        },
        "retrieval": retrieval_eval.aggregate_recall(rows, group_key="category"),
        "latency": latency.aggregate_latency(rows),
        "questions": scored_rows,
    }


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"result line {number} is not an object")
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Metronix LoCoMo JSONL results")
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_rows(load_jsonl(args.results))
    output = args.output or args.results.with_suffix(args.results.suffix + ".eval.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    r10 = retrieval_eval.gate_value(report["retrieval"], k=10)
    r5 = retrieval_eval.gate_value(report["retrieval"], k=5)
    search = report["latency"]["phases"].get("search_ms", {})
    print(
        f"LoCoMo  recall@10={_fmt(r10)}  recall@5={_fmt(r5)}  "
        f"token-F1={report['overall_score']:.4f}  "
        f"({report['retrieval']['eligible_count']}/{report['question_count']} recall-eligible)"
    )
    if report["retrieval"].get("suspect_count"):
        print(
            f"        WARNING: {report['retrieval']['suspect_count']} question(s) retrieved "
            "nothing from their own stored memory — a degraded retrieval leg, not a clean run"
        )
    if search:
        print(
            f"        search_ms  p50={search['p50_ms']:.0f}  p95={search['p95_ms']:.0f}  "
            f"max={search['max_ms']:.0f}"
        )
    print(f"Report: {output}")
    return 1 if report["error_count"] else 0


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
