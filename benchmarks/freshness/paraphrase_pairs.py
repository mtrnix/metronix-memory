"""Does a contradiction scorer leave true duplicates alone? (#516)

FactConsolidation (``conflict_pairs.py``) has no duplicates above the gate, only
updates and look-alikes. This check takes the human-labelled paraphrase pairs of
MRPC (GLUE, label 1), keeps those at or above the Reconciler's cosine gate (the
pairs it would file as ``possible_duplicate``) and counts how many each scorer
turns into a contradiction: ``nli``, the ``llm`` judge on ``--llm-sample`` of them,
and ``nli+llm``. Every flag here is a false contradiction.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return dot / norm if norm else 0.0


def main() -> None:
    import argparse
    import logging

    import pandas as pd
    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parquet", type=Path, required=True, help="GLUE MRPC split parquet")
    parser.add_argument("--gate", type=float, default=0.85)
    parser.add_argument("--nli-model", default="cross-encoder/nli-deberta-v3-xsmall")
    parser.add_argument("--nli-threshold", type=float, default=0.5)
    parser.add_argument("--llm-sample", type=int, default=0)
    parser.add_argument("--llm-timeout", type=int, default=120)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    from benchmarks.freshness.conflict_pairs import llm_judge
    from metronix.freshness.contradiction import NliContradictionScorer
    from metronix.llm.embeddings import get_cached_embedding

    frame = pd.read_parquet(args.parquet)
    frame = frame[frame["label"] == 1]
    pairs = [
        (str(a).strip(), str(b).strip())
        for a, b in zip(frame.sentence1, frame.sentence2, strict=True)
    ]
    gated = [
        (a, b)
        for a, b in pairs
        if cosine(get_cached_embedding(a), get_cached_embedding(b)) >= args.gate
    ]

    scorer = NliContradictionScorer(args.nli_model)
    scorer.contradiction_scores(gated[:1])
    started = time.perf_counter()
    scores = scorer.contradiction_scores(gated)
    nli_ms = (time.perf_counter() - started) * 1000 / max(1, len(gated))
    nli_flag = [s >= args.nli_threshold for s in scores]

    result = {
        "paraphrase_pairs": len(pairs),
        "gate": args.gate,
        "gated_pairs": len(gated),
        "nli_false_contradictions": sum(nli_flag),
        "nli_ms_per_pair": round(nli_ms, 1),
    }
    if args.llm_sample:
        rng = random.Random(args.seed)
        index = rng.sample(range(len(gated)), min(args.llm_sample, len(gated)))
        verdicts, llm_s = llm_judge([gated[i] for i in index], args.llm_timeout)
        result["llm_sample"] = {
            "pairs": len(index),
            "llm_false_contradictions": sum(verdicts),
            "nli_false_contradictions": sum(nli_flag[i] for i in index),
            "nli+llm_false_contradictions": sum(
                v and nli_flag[i] for i, v in zip(index, verdicts, strict=True)
            ),
            "nli+llm_judge_calls": sum(nli_flag[i] for i in index),
            "llm_s_per_pair": round(llm_s, 2),
        }

    print(json.dumps(result, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
