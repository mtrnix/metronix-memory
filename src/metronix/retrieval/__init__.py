"""Retrieval package — search pipeline, scoring, entity resolution."""

from metronix.retrieval.context import assemble_context
from metronix.retrieval.fallback import GracefulRetriever
from metronix.retrieval.hybrid import rrf_fusion
from metronix.retrieval.scoring import compute_signal_score
from metronix.retrieval.search import hybrid_search_and_answer, hybrid_search_and_answer_sync

__all__ = [
    "hybrid_search_and_answer",
    "hybrid_search_and_answer_sync",
    "rrf_fusion",
    "compute_signal_score",
    "assemble_context",
    "GracefulRetriever",
]
