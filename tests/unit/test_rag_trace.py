"""Unit tests for retrieval/trace.py — RagTrace accumulator + pure builders."""

from __future__ import annotations

import json
from uuid import UUID

from metronix.retrieval.trace import (
    RagTrace,
    append_trace_footer,
    build_context_phase,
    build_merge_phase,
    build_recall_phase,
    build_rerank_phase,
    footer_for,
    is_trace_enabled,
)

_TID = UUID("11111111-1111-1111-1111-111111111111")


def test_phase_appends_in_order():
    t = RagTrace(trace_id=_TID)
    t.phase("a", x=1)
    t.phase("b", y=2)
    assert [p["name"] for p in t.phases] == ["a", "b"]
    assert t.phases[0] == {"name": "a", "x": 1}


def test_set_input_and_to_dict_shape():
    t = RagTrace(trace_id=_TID, source="oai_compat", workspace_id="ws", user_id="u")
    t.set_input(raw_user_message="hi", history=["prev"], composite_query="hi")
    t.phase("classify", output={"profile": "mixed"})
    t.total_ms = 12.5
    d = t.to_dict()
    assert d["trace_id"] == str(_TID)
    assert d["source"] == "oai_compat"
    assert d["workspace_id"] == "ws"
    assert d["input"]["raw_user_message"] == "hi"
    assert d["total_ms"] == 12.5
    assert d["phases"][0]["name"] == "classify"


def test_footer_contains_id():
    f = footer_for(_TID)
    assert str(_TID) in f
    assert f.startswith("\n\n")


def test_append_trace_footer_branches():
    t = RagTrace(trace_id=_TID)
    # appends when a trace exists and footer is enabled
    out = append_trace_footer("ans", t, enabled=True)
    assert out == "ans" + footer_for(_TID)
    assert str(_TID) in out
    # no-op when footer disabled (capture still on)
    assert append_trace_footer("ans", t, enabled=False) == "ans"
    # no-op when there is no trace (capture off)
    assert append_trace_footer("ans", None, enabled=True) == "ans"


def test_is_trace_enabled_reflects_setting(monkeypatch):
    from metronix.core import config

    monkeypatch.setattr(config.get_settings(), "rag_trace_enabled", False, raising=False)
    assert is_trace_enabled() is False


def test_build_recall_phase_summarises_candidates():
    dense = [
        {
            "chunk_id": "c1",
            "doc_label": "DOC-1",
            "score": 0.9,
            "channel": "dense",
            "memory": {
                "id": "c1",
                "doc_label": "DOC-1",
                "title": "T1",
                "text": "full text",
                "type": "jira",
            },
        }
    ]
    phase = build_recall_phase(dense, [], [], [])
    assert phase["name"] == "recall"
    assert phase["channels"]["dense"]["count"] == 1
    cand = phase["channels"]["dense"]["candidates"][0]
    assert cand["chunk_id"] == "c1"
    assert cand["text"] == "full text"
    assert cand["raw_score"] == 0.9
    # source is derived from the hit's "type" key (cf. search._result_type)
    assert cand["source"] == "jira"
    assert phase["channels"]["exact"]["count"] == 0


def test_build_merge_phase_includes_signals_and_dropped():
    merged = [
        {
            "chunk_id": "c1",
            "doc_label": "DOC-1",
            "channels": ["dense", "graph"],
            "channel_scores": {"dense": 0.8, "graph": 0.3},
            "signal_score": 0.55,
            "memory": {"id": "c1", "doc_label": "DOC-1", "text": "txt"},
        }
    ]
    components = {"c1": {"recency": 1.0, "balance": 0.5, "freshness": 0.25}}
    phase = build_merge_phase(
        merged,
        weights={"dense_weight": 0.35},
        signal_components=components,
        dropped_ids=["c1"],
        freshness_weight=0.1,
    )
    assert phase["name"] == "merge_and_score"
    c = phase["candidates"][0]
    assert c["found_by"] == ["dense", "graph"]
    assert c["channel_scores"] == {"dense": 0.8, "graph": 0.3}
    assert c["recency"] == 1.0
    assert c["balance"] == 0.5
    assert c["freshness"] == 0.25
    assert c["signal_score"] == 0.55
    assert phase["dropped_by_min_signal"] == ["c1"]


def test_build_merge_phase_serialises_the_freshness_inputs():
    """MTRNIX-417: freshness_weight and the per-candidate freshness_score must
    both land in the trace, or a merge_and_score signal_score can't be
    recomputed from the payload (toomij99, PR #448)."""
    merged = [
        {
            "chunk_id": "c1",
            "channels": ["dense"],
            "channel_scores": {"dense": 0.8},
            "signal_score": 0.7,
            "memory": {"id": "c1", "text": "txt"},
        },
        {
            "chunk_id": "c2",
            "channels": ["dense"],
            "channel_scores": {"dense": 0.4},
            "signal_score": 0.3,
            "memory": {"id": "c2", "text": "txt"},
        },
    ]
    phase = build_merge_phase(
        merged,
        weights={"dense_weight": 0.35, "recency_weight": 0.1},
        signal_components={"c1": {"recency": 1.0, "balance": 0.5, "freshness": 0.25}},
        dropped_ids=[],
        freshness_weight=0.2,
    )
    assert phase["weights"]["freshness_weight"] == 0.2
    by_id = {c["chunk_id"]: c for c in phase["candidates"]}
    assert by_id["c1"]["freshness"] == 0.25
    # c2 has no signal_components entry — freshness serialises as None, not a
    # silent 1.0 that would misrepresent what was scored.
    assert by_id["c2"]["freshness"] is None


def test_build_rerank_phase_marks_kept():
    base = [
        {"id": "c1", "doc_label": "DOC-1", "rerank_score": 0.9, "text": "t"},
        {"id": "c2", "doc_label": "DOC-2", "rerank_score": 0.1, "text": "t"},
    ]
    score_map = {"c1": 0.7, "c2": 0.2}
    phase = build_rerank_phase(base, score_map, pool_size=2, enabled=True)
    assert phase["name"] == "rerank"
    assert phase["enabled"] is True
    assert phase["pool_size"] == 2
    ids = {c["chunk_id"]: c for c in phase["candidates"]}
    assert ids["c1"]["rerank_score"] == 0.9
    assert ids["c1"]["final_score"] == 0.7
    assert ids["c1"]["kept"] is True


def test_to_dict_is_json_serialisable():
    """The persisted payload must round-trip through JSON (it lands in JSONB)."""
    t = RagTrace(trace_id=_TID, source="oai_compat", workspace_id="ws")
    t.set_input(raw_user_message="q", history=[], composite_query="q")
    t.phase(
        **build_recall_phase(
            [
                {
                    "chunk_id": "c1",
                    "score": 0.9,
                    "memory": {"id": "c1", "doc_label": "D", "text": "t"},
                }
            ],
            [],
            [],
            [],
        )
    )
    t.phase(
        **build_merge_phase(
            [
                {
                    "chunk_id": "c1",
                    "channels": ["dense"],
                    "channel_scores": {"dense": 0.9},
                    "signal_score": 0.5,
                    "memory": {"id": "c1", "text": "t"},
                }
            ],
            weights={"dense_weight": 0.35},
            signal_components={"c1": {"recency": 1.0, "balance": 0.5}},
            dropped_ids=[],
            freshness_weight=0.0,
        )
    )
    # Must not raise — proves no datetime/UUID/object leaked into the payload.
    dumped = json.dumps(t.to_dict())
    assert '"trace_id"' in dumped


def test_build_context_phase_splits_roles():
    frags = [
        {"text": "p", "doc_label": "DOC-1", "evidence_marker": "PRIMARY"},
        {"text": "s", "doc_label": "DOC-2", "evidence_marker": "SUPPORTING"},
    ]
    phase = build_context_phase(frags, [], [], [], assembled_prompt="PROMPT")
    assert phase["name"] == "context_assembly"
    assert len(phase["primary_fragments"]) == 1
    assert len(phase["supporting_fragments"]) == 1
    assert phase["assembled_prompt"] == "PROMPT"
