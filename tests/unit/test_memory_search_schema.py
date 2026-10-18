"""Both response models must require and preserve explicit search health."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from metronix.api.routes.memory import MemorySearchResponse
from metronix.mcp.tools.models import MemorySearchToolResponse


@pytest.mark.parametrize("model", [MemorySearchResponse, MemorySearchToolResponse])
def test_missing_diagnostics_cannot_default_to_healthy(model):
    with pytest.raises(ValidationError):
        model(results=[], count=0)


@pytest.mark.parametrize("model", [MemorySearchResponse, MemorySearchToolResponse])
def test_serialized_diagnostics_preserve_unknown_retryability(model):
    legs = {
        "qdrant": {"status": "failed", "reason": "backend_error", "retryable": None},
        "graph": {
            "status": "ok",
            "reason": None,
            "retryable": None,
            "hydration": {
                "status": "unavailable",
                "retrieved": 1,
                "resolved": 0,
                "unavailable": 1,
                "invalid": 0,
            },
        },
        "session": {"status": "skipped", "reason": None, "retryable": None},
    }
    response = model(results=[], count=0, partial=True, legs=legs)
    assert response.model_dump(mode="json") == {
        "results": [],
        "count": 0,
        "partial": True,
        "legs": legs,
    }
