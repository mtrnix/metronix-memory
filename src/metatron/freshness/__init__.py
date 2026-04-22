"""Shared freshness pipeline (MTRNIX-313, Phase B).

Promoted from ``metatron.memory.freshness`` so that memory and KB freshness
workers share one code path. The memory subtree keeps producer + worker +
adapter; stages, coordination, decision engine, metrics, and apply_decision
live here and are adapter-agnostic.
"""

from __future__ import annotations

from metatron.freshness import metrics
from metatron.freshness.apply_decision import apply_decision
from metatron.freshness.coordination import CoordinationStore, queue_key_for
from metatron.freshness.decision_engine import (
    DecisionEngine,
    LLMBackedDecisionEngine,
    RuleBasedDecisionEngine,
    build_default_decision_engine,
)
from metatron.freshness.stages.curator import Curator
from metatron.freshness.stages.linker import Linker
from metatron.freshness.stages.monitor import FreshnessMonitor
from metatron.freshness.stages.reconciler import Reconciler
from metatron.freshness.targets import (
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
