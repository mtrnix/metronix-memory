"""Explicit detailed outcomes for tests that isolate transport serialization."""

from metronix.core.models import (
    GraphHydrationHealth,
    GraphHydrationStatus,
    GraphSearchLegHealth,
    MemorySearchOutcome,
    MemorySearchResult,
    SearchLegHealth,
    SearchLegsHealth,
    SearchLegStatus,
)


def healthy_search_outcome(results: list[MemorySearchResult]) -> MemorySearchOutcome:
    return MemorySearchOutcome(
        results=results,
        partial=False,
        legs=SearchLegsHealth(
            qdrant=SearchLegHealth(SearchLegStatus.OK, None, None),
            graph=GraphSearchLegHealth(
                SearchLegStatus.OK,
                None,
                None,
                GraphHydrationHealth(GraphHydrationStatus.OK, 0, 0, 0, 0),
            ),
            session=SearchLegHealth(SearchLegStatus.SKIPPED, None, None),
        ),
    )
