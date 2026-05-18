"""Integration tests for AsocVisibilityFilter against a live ASOC REST server.

Skip-gated: tests only run when ``METATRON_ASOC_VISIBILITY_INTEGRATION_TEST_URL`` is set.

Usage::

    METATRON_ASOC_VISIBILITY_INTEGRATION_TEST_URL=https://asoc-dev.example.com \\
    METATRON_ASOC_VISIBILITY_INTEGRATION_TEST_JWT=<valid-user-jwt> \\
    pytest tests/integration/test_asoc_visibility_live.py -v -m integration

Requires a valid ASOC user JWT that the target REST server will accept at
``POST /api/v1/visibility/filter``.
"""

from __future__ import annotations

import os

import pytest

_INTEGRATION_URL = os.getenv("METATRON_ASOC_VISIBILITY_INTEGRATION_TEST_URL", "")
_INTEGRATION_JWT = os.getenv("METATRON_ASOC_VISIBILITY_INTEGRATION_TEST_JWT", "")

if not _INTEGRATION_URL:
    pytest.skip(
        "METATRON_ASOC_VISIBILITY_INTEGRATION_TEST_URL not set — "
        "skipping live ASOC visibility tests",
        allow_module_level=True,
    )

from metatron.integrations.asoc_visibility import (  # noqa: E402
    AsocVisibilityFilter,
    VisibilityFilterAuthError,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_filter() -> AsocVisibilityFilter:
    return AsocVisibilityFilter(
        base_url=_INTEGRATION_URL,
        timeout_seconds=10.0,
        batch_size=50,
        retry_attempts=1,
    )


def _make_asoc_chunk(entity_type: str, entity_id: str) -> dict:
    return {
        "chunk_id": f"{entity_type}-{entity_id}",
        "doc_label": f"asoc:{entity_type}-{entity_id}",
        "memory": {
            "source_type": "asoc",
            "metadata": {
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        },
        "channels": ["dense"],
        "channel_scores": {"dense": 0.9},
    }


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestAsocVisibilityFilterLive:
    async def test_health_check_returns_true(self) -> None:
        """Endpoint /api/v1/visibility/filter must respond with 401 or 405 on GET."""
        f = _make_filter()
        result = await f.health_check()
        await f.aclose()
        assert result is True, (
            f"health_check() returned False — is {_INTEGRATION_URL}/api/v1/visibility/filter "
            "reachable and returning 401/405 on GET?"
        )

    async def test_filter_with_valid_jwt_returns_list(self) -> None:
        """Filter with a real JWT must return a result without raising."""
        if not _INTEGRATION_JWT:
            pytest.skip("METATRON_ASOC_VISIBILITY_INTEGRATION_TEST_JWT not set")

        f = _make_filter()
        # Use a project entity — minimal overhead, and all deployed servers should have projects.
        chunks = [_make_asoc_chunk("project", "test-proj-1")]

        try:
            result, stats = await f.filter_chunks(_INTEGRATION_JWT, chunks)
            # Result can be empty (project not visible) or have 1 item — both are valid.
            # The important thing is that no exception was raised.
            assert isinstance(result, list)
            assert stats.input_count == 1
            assert stats.batches_issued >= 1
        finally:
            await f.aclose()

    async def test_filter_with_invalid_jwt_raises_auth_error(self) -> None:
        """Sending a garbage JWT must raise VisibilityFilterAuthError (401/403)."""
        f = _make_filter()
        chunks = [_make_asoc_chunk("project", "proj-1")]

        try:
            with pytest.raises(VisibilityFilterAuthError):
                await f.filter_chunks("invalid.jwt.token", chunks)
        finally:
            await f.aclose()
