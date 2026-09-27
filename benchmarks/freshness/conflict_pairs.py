"""Can the freshness Reconciler tell a contradiction from a duplicate? (#516)

Replays the Reconciler's candidate step on MemoryAgentBench FactConsolidation
(MQuAKE facts plus counterfactual edits of some of them, e.g. "X is married to A"
and later "X is married to B"): every fact is embedded like a memory record
(``get_cached_embedding``, raw text), each fact's top-k neighbours at or above the
cosine gate become candidate pairs, and each pair is labelled from the parsed
(relation, subject, object) triples:

``conflict``  same relation and subject, different object (an update);
``same``      identical triple (a duplicate);
``other``     anything else above the gate (e.g. the same relation for another
              subject), which the cosine-only Reconciler files as a duplicate.

Configurations scored on the gated pairs:

- ``cosine``: today's Reconciler, every gated pair is ``possible_duplicate``;
- ``nli``: ``NliContradictionScorer`` above ``--nli-threshold`` is a contradiction;
- ``llm``: an LLM judge (``chat_completion``, e.g. qwen2.5:3b on Ollama) on a
  sample of the pairs (``--llm-sample``), the expensive baseline.

Also reported: how many of all conflict pairs pass the gate at all (a contradiction
below the gate never reaches any classifier), and cost per pair.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path

# Relation templates of MQuAKE (princeton-nlp/MQuAKE, requested_rewrite.prompt),
# the source of FactConsolidation. Spelling as in the data.
MQUAKE_TEMPLATES = (
    "The author of {} is",
    "The capital of {} is",
    "The chairperson of {} is",
    "The chief executive officer of {} is",
    "The company that produced {} is",
    "The director of {} is",
    "The head coach of {} is",
    "The headquarters of {} is located in the city of",
    "The name of the current head of state in {} is",
    "The name of the current head of the {} government is",
    "The official language of {} is",
    "The origianl broadcaster of {} is",
    "The original language of {} is",
    "The type of music that {} plays is",
    "The univeristy where {} was educated is",
    "The {} is",
    "{} died in the city of",
    "{} is a citizen of",
    "{} is affiliated with the religion of",
    "{} is associated with the sport of",
    "{} is employed by",
    "{} is famous for",
    "{} is located in the continent of",
    "{} is married to",
    "{} plays the position of",
    "{} speaks the language of",
    "{} was born in the city of",
    "{} was created by",
    "{} was created in the country of",
    "{} was developed by",
    "{} was founded by",
    "{} was founded in the city of",
    "{} was performed by",
    "{} was written in the language of",
    "{} worked in the city of",
    "{} works in the field of",
    "{}'s child is",
)

JUDGE_PROMPT = (
    "Two statements from an agent's memory:\n"
    "A: {a}\nB: {b}\n\n"
    "Do A and B contradict each other, i.e. can they not both be true at the same "
    "time? Answer with one word: yes or no."
)


def _compile(templates: tuple[str, ...]) -> list[tuple[str, re.Pattern[str]]]:
    # Most specific first: "The {} is" would otherwise swallow "The capital of X is Y".
    ordered = sorted(templates, key=lambda t: -len(t.replace("{}", "")))
    compiled = []
    for template in ordered:
        before, after = template.split("{}")
        pattern = re.compile("^" + re.escape(before) + "(.+?)" + re.escape(after) + " (.+)$")
        compiled.append((template, pattern))
    return compiled


_PATTERNS = _compile(MQUAKE_TEMPLATES)


def parse_facts(context: str) -> list[str]:
    """Numbered facts of a FactConsolidation context, in serial order."""
    facts = []
    for line in context.splitlines():
        match = re.match(r"^\s*(\d+)\.\s+(.*\S)\s*$", line)
        if match:
            facts.append(match.group(2))
    return facts


def parse_triple(fact: str) -> tuple[str, str, str] | None:
    text = fact.rstrip(".").strip()
    for template, pattern in _PATTERNS:
        match = pattern.match(text)
        if match:
            return template, match.group(1).strip(), match.group(2).strip()
    return None


def label_pair(a: tuple[str, str, str] | None, b: tuple[str, str, str] | None) -> str:
    if a is None or b is None:
        return "other"
    if a[:2] == b[:2]:
        return "same" if a[2] == b[2] else "conflict"
    return "other"


def conflict_pairs(triples: list[tuple[str, str, str] | None]) -> set[tuple[int, int]]:
    """All index pairs (i < j) that state different objects for one relation+subject."""
    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, triple in enumerate(triples):
        if triple is not None:
            by_key[triple[:2]].append(index)
    out = set()
    for indices in by_key.values():
        for x, i in enumerate(indices):
            for j in indices[x + 1 :]:
                if triples[i][2] != triples[j][2]:
                    out.add((i, j))
    return out


def gated_pairs(vectors, gate: float, top_k: int) -> dict[tuple[int, int], float]:
    """Unordered pairs among each item's top-k cosine neighbours at or above ``gate``."""
    import numpy as np

    matrix = np.asarray(vectors, dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    sims = matrix @ matrix.T
    np.fill_diagonal(sims, -1.0)
    out: dict[tuple[int, int], float] = {}
    for i in range(len(matrix)):
        neighbours = np.argsort(-sims[i])[:top_k]
        for j in neighbours:
            if sims[i, j] < gate:
                break
            key = (min(i, int(j)), max(i, int(j)))
            out[key] = float(sims[i, j])
    return out


def prf(predicted: set, actual: set) -> dict:
    tp = len(predicted & actual)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(actual) if actual else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted": len(predicted),
        "true_positive": tp,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def llm_judge(pairs: list[tuple[str, str]], timeout: int) -> tuple[list[bool], float]:
    from metronix.llm import chat_completion

    verdicts = []
    started = time.perf_counter()
    for a, b in pairs:
        answer = chat_completion(
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(a=a, b=b)}],
            temperature=0.0,
            max_tokens=3,
            timeout=timeout,
            call_site="freshness_conflict_benchmark",
        )
        verdicts.append(answer.strip().lower().startswith("yes"))
    return verdicts, (time.perf_counter() - started) / max(1, len(pairs))


def main() -> None:
    import argparse
    import logging

    import pandas as pd
    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--parquet", type=Path, required=True, help="MemoryAgentBench Conflict_Resolution parquet"
    )
    parser.add_argument("--source", default="factconsolidation_sh_32k")
    parser.add_argument("--gate", type=float, default=0.85)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--nli-model", default="cross-encoder/nli-deberta-v3-xsmall")
    parser.add_argument("--nli-threshold", type=float, default=0.5)
    parser.add_argument(
        "--llm-sample", type=int, default=0, help="pairs judged by the LLM (0 = skip)"
    )
    parser.add_argument("--llm-timeout", type=int, default=120)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    from metronix.freshness.contradiction import NliContradictionScorer
    from metronix.llm.embeddings import get_cached_embedding

    frame = pd.read_parquet(args.parquet)
    rows = frame[frame["metadata"].map(lambda m: m["source"]) == args.source]
    if rows.empty:
        raise SystemExit(f"no context with source {args.source}")
    facts = parse_facts(rows.iloc[0]["context"])
    triples = [parse_triple(f) for f in facts]
    conflicts = conflict_pairs(triples)

    started = time.perf_counter()
    vectors = [get_cached_embedding(fact) for fact in facts]
    embed_ms = (time.perf_counter() - started) * 1000 / len(facts)
    gated = gated_pairs(vectors, args.gate, args.top_k)
    labels = {pair: label_pair(triples[pair[0]], triples[pair[1]]) for pair in gated}
    gated_conflicts = {pair for pair, label in labels.items() if label == "conflict"}

    scorer = NliContradictionScorer(args.nli_model)
    scorer.contradiction_scores([(facts[0], facts[1])])  # load outside the timing
    ordered = sorted(gated)
    started = time.perf_counter()
    scores = scorer.contradiction_scores([(facts[i], facts[j]) for i, j in ordered])
    nli_ms = (time.perf_counter() - started) * 1000 / max(1, len(ordered))
    nli_predicted = {
        pair for pair, s in zip(ordered, scores, strict=True) if s >= args.nli_threshold
    }

    result = {
        "source": args.source,
        "facts": len(facts),
        "facts_parsed": sum(t is not None for t in triples),
        "conflict_pairs": len(conflicts),
        "gate": args.gate,
        "top_k": args.top_k,
        "gated_pairs": len(gated),
        "gated_by_label": {
            k: sum(v == k for v in labels.values()) for k in ("conflict", "same", "other")
        },
        "conflicts_reaching_gate": round(len(gated_conflicts) / len(conflicts), 3)
        if conflicts
        else None,
        "cost_ms_per_item": {"embed": round(embed_ms, 1), "nli_pair": round(nli_ms, 1)},
        "on_gated_pairs": {
            "cosine": prf(set(), gated_conflicts),
            "nli": prf(nli_predicted, gated_conflicts),
        },
        "nli_by_label": {
            label: {
                "pairs": sum(labels[p] == label for p in ordered),
                "flagged_contradiction": sum(
                    labels[p] == label and s >= args.nli_threshold
                    for p, s in zip(ordered, scores, strict=True)
                ),
            }
            for label in ("conflict", "same", "other")
        },
    }

    if args.llm_sample:
        rng = random.Random(args.seed)
        sample = rng.sample(ordered, min(args.llm_sample, len(ordered)))
        verdicts, llm_s = llm_judge([(facts[i], facts[j]) for i, j in sample], args.llm_timeout)
        sample_conflicts = {p for p in sample if labels[p] == "conflict"}
        nli_on_sample = {p for p in sample if p in nli_predicted}
        result["llm_sample"] = {
            "pairs": len(sample),
            "conflicts": len(sample_conflicts),
            "llm": prf({p for p, v in zip(sample, verdicts, strict=True) if v}, sample_conflicts),
            "nli": prf(nli_on_sample, sample_conflicts),
            "llm_s_per_pair": round(llm_s, 2),
        }

    print(json.dumps(result, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
