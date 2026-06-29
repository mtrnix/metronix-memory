"""RAG debug trace — accumulator + pure phase builders (MTRNIX).

A ``RagTrace`` is seeded by chat entry-points with the request ``correlation_id``
and passed into ``hybrid_search_and_answer``, which fills context fields and
appends one dict per pipeline phase. The full structure is persisted to
``rag_debug_traces`` and read back by ``/api/v1/traces``. Self-contained:
deliberately duplicates prompt/answer rather than joining to llm_generation_log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from metronix.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from metronix.llm.telemetry import TelemetryContext


def is_trace_enabled() -> bool:
    """True when RAG debug-trace capture is on (master flag)."""
    return get_settings().rag_trace_enabled


def footer_for(trace_id: UUID) -> str:
    """The user-visible answer footer carrying the trace id."""
    return f"\n\n— trace: {trace_id}"


def maybe_create_trace(
    tctx: TelemetryContext,
    *,
    raw_user_message: str,
    composite_query: str | None = None,
    history: list[str] | None = None,
) -> RagTrace | None:
    """Seed a RagTrace from the request's telemetry context, or None if capture is off.

    Single entry-point helper so chat / OAI (stream + non-stream) don't each
    repeat the enabled-check + ``RagTrace(...)`` + ``set_input`` dance.
    """
    if not is_trace_enabled() or tctx.correlation_id is None:
        return None
    trace = RagTrace(trace_id=tctx.correlation_id)
    trace.set_input(
        raw_user_message=raw_user_message,
        history=history,
        composite_query=composite_query,
    )
    return trace


def append_trace_footer(text: str, trace: RagTrace | None, *, enabled: bool) -> str:
    """Append the ``— trace: <id>`` footer when a trace exists and the footer is enabled."""
    if trace is None or not enabled:
        return text
    return text + footer_for(trace.trace_id)


@dataclass
class RagTrace:
    """Mutable per-request trace accumulator.

    Entry-points set only ``trace_id`` and ``set_input(...)``; ``source`` /
    ``workspace_id`` / ``user_id`` / ``agent_id`` are filled inside the pipeline
    (single source of truth — they cannot diverge from what the pipeline used).
    """

    trace_id: UUID
    source: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    phases: list[dict[str, Any]] = field(default_factory=list)
    total_ms: float = 0.0

    def set_input(
        self,
        *,
        raw_user_message: str,
        history: list[str] | None = None,
        composite_query: str | None = None,
    ) -> None:
        self.input = {
            "raw_user_message": raw_user_message,
            "history": history or [],
            "composite_query": composite_query,
        }

    def phase(self, name: str, **data: Any) -> None:
        """Append a phase. Cheap, never raises."""
        self.phases.append({"name": name, **data})

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": str(self.trace_id),
            "source": self.source,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "input": self.input,
            "phases": self.phases,
            "total_ms": self.total_ms,
        }


# ---------------------------------------------------------------------------
# Pure phase builders — take pipeline-local data, return JSONB-serialisable dicts.
# Defensive .get() everywhere: candidate dicts are flat Qdrant hits whose exact
# keys vary by source; missing keys degrade to "" / 0.0, never KeyError.
# ---------------------------------------------------------------------------


def _candidate_summary(mem: Mapping[str, Any], *, score: float | None = None) -> dict[str, Any]:
    """Summarise one recall candidate (full text retained per design)."""
    raw_payload = mem.get("payload")
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
    raw_metadata = mem.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    summary: dict[str, Any] = {
        "chunk_id": str(mem.get("id", "")),
        "doc_label": mem.get("doc_label", "") or payload.get("doc_label", ""),
        "title": mem.get("title", "") or payload.get("title", ""),
        # Source type lives under "type" in these hit dicts (cf. search._result_type),
        # with source_type/source as secondary fallbacks.
        "source": (
            mem.get("type")
            or mem.get("source_type")
            or mem.get("source")
            or payload.get("type")
            or payload.get("source_type")
            or metadata.get("type")
            or ""
        ),
        "text": mem.get("text", "") or mem.get("memory", "") or payload.get("text", ""),
    }
    if score is not None:
        summary["raw_score"] = score
    return summary


def build_recall_phase(
    dense: Sequence[Mapping[str, Any]],
    exact: Sequence[Mapping[str, Any]],
    metadata: Sequence[Mapping[str, Any]],
    graph: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """One phase aggregating the four recall channels with per-candidate detail."""

    def _chan(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(results),
            "candidates": [
                _candidate_summary(r.get("memory", {}), score=r.get("score")) for r in results
            ],
        }

    return {
        "name": "recall",
        "channels": {
            "dense": _chan(dense),
            "exact": _chan(exact),
            "metadata": _chan(metadata),
            "graph": _chan(graph),
        },
    }


def build_merge_phase(
    merged: Sequence[Mapping[str, Any]],
    *,
    weights: dict[str, float],
    signal_components: dict[str, dict[str, float]],
    dropped_ids: list[str],
) -> dict[str, Any]:
    """Merged-and-scored candidates with per-signal breakdown + confidence drops."""
    candidates: list[dict[str, Any]] = []
    for mr in merged:
        cid = mr["chunk_id"]
        comp = signal_components.get(cid, {})
        candidates.append(
            {
                **_candidate_summary(mr.get("memory", {})),
                "found_by": list(mr.get("channels", [])),
                "channel_scores": dict(mr.get("channel_scores", {})),
                "recency": comp.get("recency"),
                "balance": comp.get("balance"),
                "signal_score": mr.get("signal_score", 0.0),
            }
        )
    return {
        "name": "merge_and_score",
        "weights": weights,
        "candidates": candidates,
        "dropped_by_min_signal": list(dropped_ids),
    }


def build_rerank_phase(
    base: Sequence[Mapping[str, Any]],
    score_map: dict[str, float],
    *,
    pool_size: int,
    enabled: bool,
) -> dict[str, Any]:
    """Rerank candidates with signal/rerank/final scores and kept flags."""
    candidates: list[dict[str, Any]] = []
    for r in base:
        cid = str(r.get("id", ""))
        candidates.append(
            {
                **_candidate_summary(r),
                "rerank_score": r.get("rerank_score", 0.0),
                "final_score": score_map.get(cid, 0.0),
                "kept": True,
            }
        )
    return {
        "name": "rerank",
        "enabled": enabled,
        "pool_size": pool_size,
        "candidates": candidates,
    }


def build_context_phase(
    frags: Sequence[Mapping[str, Any]],
    g_ents: Sequence[Any],
    g_rels: Sequence[Any],
    g_docs: Sequence[Any],
    *,
    assembled_prompt: str,
) -> dict[str, Any]:
    """Final fragments (split by evidence role) + graph context + the LLM prompt."""

    def _frag(f: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "doc_label": f.get("doc_label", ""),
            "title": f.get("title", ""),
            "text": f.get("text", ""),
        }

    primary = [_frag(f) for f in frags if f.get("evidence_marker") == "PRIMARY"]
    supporting = [_frag(f) for f in frags if f.get("evidence_marker") != "PRIMARY"]
    return {
        "name": "context_assembly",
        "primary_fragments": primary,
        "supporting_fragments": supporting,
        "graph": {"entities": list(g_ents), "relations": list(g_rels), "docs": list(g_docs)},
        "assembled_prompt": assembled_prompt,
    }
