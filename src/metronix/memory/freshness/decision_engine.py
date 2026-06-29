"""Compat shim — moved to :mod:`metronix.freshness.decision_engine` (MTRNIX-313)."""

from __future__ import annotations

from metronix.freshness.decision_engine import (  # noqa: F401
    DecisionEngine,
    LLMBackedDecisionEngine,
    RuleBasedDecisionEngine,
    apply_decision,
    build_default_decision_engine,
)

__all__ = [
    "DecisionEngine",
    "LLMBackedDecisionEngine",
    "RuleBasedDecisionEngine",
    "apply_decision",
    "build_default_decision_engine",
]
