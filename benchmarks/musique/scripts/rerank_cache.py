"""Persistent cache for cross-encoder scores, for repeated retrieval-harness runs.

``bge-reranker-v2-m3`` on CPU dominates a pipeline run, and a fusion comparison scores
the same (query, passage) pairs once per variant. The cross-encoder is deterministic,
so a run served from the cache is identical to one that calls the model: the cache
wraps ``predict`` and only the pairs it has not seen go to the model.

Keys are ``sha1(query \\0 passage)``; entries are appended to a JSONL file, one
``{"k": key, "s": score}`` per line, so concurrent readers never see a torn file and an
interrupted run keeps what it scored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def pair_key(query: str, passage: str) -> str:
    return hashlib.sha1(f"{query}\0{passage}".encode()).hexdigest()


class CachedCrossEncoder:
    """Drop-in for ``CrossEncoder.predict`` backed by a JSONL score cache."""

    def __init__(self, model: Any, path: Path | None) -> None:
        self.model = model
        self.path = path
        self.scores: dict[str, float] = {}
        self.hits = 0
        self.misses = 0
        if path is not None and path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        self.scores[entry["k"]] = float(entry["s"])

    def predict(self, pairs: Sequence[tuple[str, str]], **kwargs: Any) -> list[float]:
        keys = [pair_key(q, p) for q, p in pairs]
        missing = [i for i, k in enumerate(keys) if k not in self.scores]
        self.hits += len(keys) - len(missing)
        self.misses += len(missing)
        if missing:
            fresh = self.model.predict([pairs[i] for i in missing], **kwargs)
            new = {keys[i]: float(s) for i, s in zip(missing, fresh, strict=True)}
            self.scores.update(new)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    for k, s in new.items():
                        handle.write(json.dumps({"k": k, "s": s}) + "\n")
        return [self.scores[k] for k in keys]


def install(path: Path | None) -> CachedCrossEncoder:
    """Route ``metronix.retrieval.reranker`` through a cache (loads the model lazily)."""
    from metronix.retrieval import reranker

    class _Lazy:
        model = None

        def predict(self, pairs, **kwargs):
            if self.model is None:
                from sentence_transformers import CrossEncoder

                self.model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
            return self.model.predict(pairs, **kwargs)

    cached = CachedCrossEncoder(_Lazy(), path)
    reranker._reranker = cached
    return cached
