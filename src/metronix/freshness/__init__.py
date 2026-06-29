"""Shared freshness pipeline (MTRNIX-313, Phase B).

Promoted from ``metronix.memory.freshness`` so that memory and KB freshness
workers share one code path. The memory subtree keeps producer + worker +
adapter; stages, coordination, decision engine, metrics, and apply_decision
live here and are adapter-agnostic.
"""

from __future__ import annotations

from metronix.freshness import metrics
from metronix.freshness.apply_decision import apply_decision
from metronix.freshness.coordination import CoordinationStore, queue_key_for
from metronix.freshness.decision_engine import (
    DecisionEngine,
    LLMBackedDecisionEngine,
    RuleBasedDecisionEngine,
    build_default_decision_engine,
)
from metronix.freshness.stages.curator import Curator
from metronix.freshness.stages.linker import Linker
from metronix.freshness.stages.monitor import FreshnessMonitor
from metronix.freshness.stages.reconciler import Reconciler
from metronix.freshness.targets import (
    FreshnessTarget,
    FreshnessTargetRecord,
    SimilarityHit,
)

__all__ = [
    "CoordinationStore",
    "Curator",
    "DecisionEngine",
    "FreshnessMonitor",
    "FreshnessTarget",
    "FreshnessTargetRecord",
    "LLMBackedDecisionEngine",
    "Linker",
    "Reconciler",
    "RuleBasedDecisionEngine",
    "SimilarityHit",
    "apply_decision",
    "build_default_decision_engine",
    "metrics",
    "queue_key_for",
]
