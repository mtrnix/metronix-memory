"""Retrieval package — search pipeline, scoring, entity resolution."""

from metatron.retrieval.context import assemble_context
from metatron.retrieval.fallback import GracefulRetriever
from metatron.retrieval.hybrid import rrf_fusion
from metatron.retrieval.scoring import compute_signal_score
from metatron.retrieval.search import hybrid_search_and_answer

__all__ = [
    "hybrid_search_and_answer",
    "rrf_fusion",
    "compute_signal_score",
    "assemble_context",
    "GracefulRetriever",
]
