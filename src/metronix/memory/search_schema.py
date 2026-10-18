"""Shared public search-health schema for REST and MCP responses."""

from pydantic import BaseModel, ConfigDict, Field

from metronix.core.models import (
    GraphHydrationStatus,
    SearchFailureReason,
    SearchLegsHealth,
    SearchLegStatus,
)


class SearchLegHealthDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: SearchLegStatus
    reason: SearchFailureReason | None
    retryable: bool | None


class GraphHydrationHealthDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: GraphHydrationStatus
    retrieved: int = Field(ge=0)
    resolved: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    invalid: int = Field(ge=0)


class GraphSearchLegHealthDTO(SearchLegHealthDTO):
    hydration: GraphHydrationHealthDTO


class SearchLegsHealthDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    qdrant: SearchLegHealthDTO
    graph: GraphSearchLegHealthDTO
    session: SearchLegHealthDTO


def search_legs_to_dto(legs: SearchLegsHealth) -> SearchLegsHealthDTO:
    """Map only schema-owned diagnostic fields, never backend exception text."""
    return SearchLegsHealthDTO.model_validate(legs)
