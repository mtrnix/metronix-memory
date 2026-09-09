"""Compare two benchmark runs from the artifacts they wrote.

A run (LongMemEval or LoCoMo) leaves next to its ``answers.jsonl``:

- ``.manifest.json``      — dataset sha256, repo revision + dirty, config, and
                            the ``question_ids_sha256`` of the exact set it ran.
- ``.query_set.json``     — the ordered question-id list.
- ``.retrieval.eval.json`` (LongMemEval) / the ``retrieval`` + ``latency``
  blocks inside ``.eval.json`` (LoCoMo) — recall@k and per-phase latency.

Two runs are comparable only when every identity field matches and only the
declared retrieval mode differs (the PPR A/B variable). ``compare`` then reports
the recall@10 delta and applies the gate.

Stdlib only — this is imported from the main venv (which has no bench deps) as
well as run standalone.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MANIFEST_SUFFIX = ".manifest.json"
_QUERY_SET_SUFFIX = ".query_set.json"
_RETRIEVAL_EVAL_SUFFIX = ".retrieval.eval.json"
_ANSWER_EVAL_SUFFIX = ".eval.json"

# metrics a gate / regression check may name (higher is better)
GATE_METRICS: tuple[str, ...] = (
    "recall_at_10",
    "recall_at_5",
    "answer_metric",
)


@dataclass(frozen=True)
class RunArtifacts:
    results_path: Path
    manifest: dict[str, Any]
    query_set: dict[str, Any]
    retrieval_eval: dict[str, Any] | None
    answer_eval: dict[str, Any] | None

    @property
    def benchmark(self) -> str:
        return str(self.manifest.get("benchmark", "unknown"))


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def load_run(results_path: Path | str) -> RunArtifacts:
    """Load the sidecars for one run's ``answers.jsonl``."""
    results_path = Path(results_path)
    manifest = _load_json(results_path.with_suffix(results_path.suffix + _MANIFEST_SUFFIX))
    query_set = _load_json(results_path.with_suffix(results_path.suffix + _QUERY_SET_SUFFIX))
    if manifest is None or query_set is None:
        raise FileNotFoundError(
            f"{results_path} is missing its .manifest.json / .query_set.json — "
            "re-run the benchmark (step 1+ of the reproducible harness)"
        )
    return RunArtifacts(
        results_path=results_path,
        manifest=manifest,
        query_set=query_set,
        retrieval_eval=_load_json(
            results_path.with_suffix(results_path.suffix + _RETRIEVAL_EVAL_SUFFIX)
        ),
        answer_eval=_load_json(
            results_path.with_suffix(results_path.suffix + _ANSWER_EVAL_SUFFIX)
        ),
    )


# ---------------------------------------------------------------------------
# Normalized metrics
# ---------------------------------------------------------------------------


def _phase_percentile(latency: Mapping[str, Any] | None, phase: str, key: str) -> float | None:
    if not isinstance(latency, Mapping):
        return None
    stats = latency.get("phases", {}).get(phase)
    return stats.get(key) if isinstance(stats, Mapping) else None


def metrics(run: RunArtifacts) -> dict[str, Any]:
    """One flat shape for both benchmarks.

    ``answer_metric`` is token-F1 for LoCoMo and — when the judge ran — accuracy
    for LongMemEval; ``None`` when the judge output is not available.
    """
    recall_report: Mapping[str, Any] | None
    latency_report: Mapping[str, Any] | None
    answer_metric: float | None
    answer_metric_name: str
    error_count = 0

    if run.benchmark == "locomo":
        ev = run.answer_eval or {}
        recall_report = ev.get("retrieval")
        latency_report = ev.get("latency")
        answer_metric = ev.get("overall_score")
        answer_metric_name = "token_f1"
        error_count = int(ev.get("error_count", 0) or 0)
    else:  # longmemeval
        recall_report = run.retrieval_eval
        latency_report = run.retrieval_eval.get("latency") if run.retrieval_eval else None
        answer_metric, answer_metric_name = _longmemeval_answer_metric(run)

    recall = recall_report.get("recall", {}) if isinstance(recall_report, Mapping) else {}
    eligible = (
        int(recall_report.get("eligible_count", 0)) if isinstance(recall_report, Mapping) else 0
    )
    suspect = (
        int(recall_report.get("suspect_count", 0)) if isinstance(recall_report, Mapping) else 0
    )

    return {
        "benchmark": run.benchmark,
        "recall_at_10": recall.get("10"),
        "recall_at_5": recall.get("5"),
        "recall_eligible_count": eligible,
        "search_suspect_count": suspect,
        "search_latency_p50_ms": _phase_percentile(latency_report, "search_ms", "p50_ms"),
        "search_latency_p95_ms": _phase_percentile(latency_report, "search_ms", "p95_ms"),
        "total_latency_p95_ms": _phase_percentile(latency_report, "total_ms", "p95_ms"),
        "answer_metric": answer_metric,
        "answer_metric_name": answer_metric_name,
        "error_count": error_count,
    }


def _longmemeval_answer_metric(run: RunArtifacts) -> tuple[float | None, str]:
    """LongMemEval judge accuracy from a ``*.eval-<judge>`` sidecar, if present."""
    for path in sorted(run.results_path.parent.glob(f"{run.results_path.name}.eval-*")):
        labelled = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        marks = [
            1 if isinstance(row, dict) and row.get("autoeval_label", {}).get("label") else 0
            for row in labelled
        ]
        if marks:
            return sum(marks) / len(marks), "judge_accuracy"
    return None, "judge_accuracy"


# ---------------------------------------------------------------------------
# Comparability
# ---------------------------------------------------------------------------


def check_comparable(
    baseline: RunArtifacts,
    current: RunArtifacts,
    *,
    allow_dirty: bool = False,
    allow_same_mode: bool = False,
) -> list[str]:
    """Reasons the two runs are NOT comparable (empty list == comparable)."""
    reasons: list[str] = []

    def _cmp(label: str, a: Any, b: Any) -> None:
        if a != b:
            reasons.append(f"{label} differs: {a!r} vs {b!r}")

    bm, cm = baseline.manifest, current.manifest
    _cmp("benchmark", bm.get("benchmark"), cm.get("benchmark"))
    _cmp("dataset sha256", _get(bm, "dataset", "sha256"), _get(cm, "dataset", "sha256"))
    _cmp(
        "question set (question_ids_sha256)",
        baseline.query_set.get("question_ids_sha256"),
        current.query_set.get("question_ids_sha256"),
    )
    _cmp(
        "repository revision",
        _get(bm, "repository", "revision"),
        _get(cm, "repository", "revision"),
    )
    for label, run in (("baseline", baseline), ("current", current)):
        if _get(run.manifest, "repository", "dirty") is True and not allow_dirty:
            reasons.append(f"{label} run was made from a dirty working tree (pass --allow-dirty)")
    for key in (
        "top_k",
        "workspace",
        "chat_model",
        "chat_base_url",
        "chat_temperature",
        "chat_max_tokens",
        "judge_model",
        "judge_base_url",
    ):
        if key in bm.get("config", {}) or key in cm.get("config", {}):
            _cmp(f"config.{key}", _get(bm, "config", key), _get(cm, "config", key))
    _cmp(
        "mcp endpoint",
        _get(bm, "stack", "mcp_endpoint_identity"),
        _get(cm, "stack", "mcp_endpoint_identity"),
    )
    # The stack probe (best-effort) — a leg run with Qdrant/Neo4j down is not a
    # clean comparison point. Missing probes on both sides are not flagged.
    b_probe = _get(bm, "stack", "probe") or {}
    c_probe = _get(cm, "stack", "probe") or {}
    if bool(b_probe.get("probe")) != bool(c_probe.get("probe")):
        reasons.append(
            "stack probe availability differs: one leg reached the server, the other did not"
        )
    for field in ("qdrant", "neo4j", "qdrant_collections"):
        b_val = b_probe.get(field)
        c_val = c_probe.get(field)
        if b_val is not None or c_val is not None:
            _cmp(f"stack probe {field}", b_val, c_val)

    base_mode = _get(bm, "stack", "operator_declared_retrieval_mode")
    cur_mode = _get(cm, "stack", "operator_declared_retrieval_mode")
    if base_mode == cur_mode and not allow_same_mode:
        reasons.append(
            f"both runs declare the same retrieval mode ({base_mode!r}) — nothing to A/B "
            "(pass --allow-same-mode for a repeatability check)"
        )

    # A run where the workspace was reset and one where it was not carry
    # different amounts of residual memory — not the same measurement.
    _cmp(
        "workspace reset",
        _get(bm, "stack", "workspace_reset"),
        _get(cm, "stack", "workspace_reset"),
    )

    for label, run in (("baseline", baseline), ("current", current)):
        run_metrics = metrics(run)
        if run_metrics["error_count"]:
            reasons.append(f"{label} run has benchmark errors — treat it as a failed leg")
        if run_metrics["search_suspect_count"]:
            reasons.append(
                f"{label} run has {run_metrics['search_suspect_count']} question(s) where the "
                "agent's own memory returned nothing — a degraded retrieval leg, not a clean run"
            )

    return reasons


def _get(mapping: Mapping[str, Any], *path: str) -> Any:
    node: Any = mapping
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


# ---------------------------------------------------------------------------
# Comparison + gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    baseline: float | None
    current: float | None
    delta: float | None


def compare(
    baseline: RunArtifacts,
    current: RunArtifacts,
    *,
    gates: Mapping[str, float] | None = None,
    max_regressions: Mapping[str, float] | None = None,
    allow_dirty: bool = False,
    allow_same_mode: bool = False,
) -> dict[str, Any]:
    gates = dict(gates or {})
    max_regressions = dict(max_regressions or {})
    _validate_metric_names(gates, max_regressions)

    incompatibilities = check_comparable(
        baseline, current, allow_dirty=allow_dirty, allow_same_mode=allow_same_mode
    )
    bm, cm = metrics(baseline), metrics(current)

    tracked = sorted(
        {"recall_at_10", "recall_at_5", "answer_metric"} | set(gates) | set(max_regressions)
    )
    deltas: dict[str, MetricDelta] = {}
    for name in tracked:
        b, c = _as_float(bm.get(name)), _as_float(cm.get(name))
        deltas[name] = MetricDelta(
            metric=name,
            baseline=b,
            current=c,
            delta=(c - b) if (b is not None and c is not None) else None,
        )

    gate_failures: list[str] = []
    for name, floor in gates.items():
        value = _as_float(cm.get(name))
        if value is None:
            gate_failures.append(f"{name}: not available in the current run")
        elif value < floor:
            gate_failures.append(f"{name}={value:.4f} is below the gate floor {floor:.4f}")

    regressions: list[str] = []
    for name, max_decline in max_regressions.items():
        d = deltas.get(name)
        if d is None or d.delta is None:
            regressions.append(f"{name}: delta not computable (metric missing in a run)")
        elif d.delta < -max_decline:
            regressions.append(f"{name} declined by {-d.delta:.4f} (> allowed {max_decline:.4f})")

    passed = not incompatibilities and not gate_failures and not regressions
    return {
        "schema_version": 1,
        "verdict": "PASS" if passed else "FAIL",
        "comparable": not incompatibilities,
        "incompatibilities": incompatibilities,
        "baseline": {
            "results": str(baseline.results_path),
            "retrieval_mode": _get(baseline.manifest, "stack", "operator_declared_retrieval_mode"),
            "run_id": baseline.manifest.get("run_id"),
        },
        "current": {
            "results": str(current.results_path),
            "retrieval_mode": _get(current.manifest, "stack", "operator_declared_retrieval_mode"),
            "run_id": current.manifest.get("run_id"),
        },
        "metrics": {
            name: {"baseline": d.baseline, "current": d.current, "delta": d.delta}
            for name, d in deltas.items()
        },
        "recall_eligible": {
            "baseline": bm["recall_eligible_count"],
            "current": cm["recall_eligible_count"],
        },
        "answer_metric_name": cm["answer_metric_name"],
        "gate_failures": gate_failures,
        "regressions": regressions,
    }


def _validate_metric_names(*groups: Mapping[str, float]) -> None:
    for group in groups:
        for name, limit in group.items():
            if name not in GATE_METRICS:
                raise ValueError(f"unknown gate metric {name!r} (choose from {GATE_METRICS})")
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit < 0:
                raise ValueError(f"gate value for {name} must be a non-negative number")


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def parse_metric_assignment(value: str) -> tuple[str, float]:
    """``recall_at_10=0.62`` -> ``("recall_at_10", 0.62)``."""
    key, _, raw = value.partition("=")
    key = key.strip()
    try:
        limit = float(raw)
    except ValueError as exc:
        raise ValueError(f"expected METRIC=NUMBER, got {value!r}") from exc
    _validate_metric_names({key: limit})
    return key, limit


def collect_assignments(values: Sequence[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for value in values:
        key, limit = parse_metric_assignment(value)
        if key in out:
            raise ValueError(f"metric {key!r} given twice")
        out[key] = limit
    return out
