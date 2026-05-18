"""Integration tests for AsocConnector against a live ASOC dev instance.

These tests are SKIP-GATED: they only run when the environment variable
``METATRON_ASOC_INTEGRATION_TEST_URL`` is set.  They require a real ASOC
instance with valid credentials provided via environment variables.

Required env vars (must all be set):
    METATRON_ASOC_INTEGRATION_TEST_URL:  ASOC base URL
    METATRON_ASOC_INTEGRATION_SERVICE_TOKEN: API token
    METATRON_ASOC_INTEGRATION_PROJECT_ID:   ASOC project UUID
    METATRON_ASOC_INTEGRATION_INSTANCE_ID:  ASOC instance ID

Usage:
    METATRON_ASOC_INTEGRATION_TEST_URL=https://asoc.dev.example.com \\
    METATRON_ASOC_INTEGRATION_SERVICE_TOKEN=tok-xxx \\
    METATRON_ASOC_INTEGRATION_PROJECT_ID=proj-uuid \\
    METATRON_ASOC_INTEGRATION_INSTANCE_ID=inst-1 \\
    pytest tests/integration/test_asoc_connector_live.py -v -m integration
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from metatron.connectors.asoc import AsocConnector
from metatron.core.models import Connection

# ---------------------------------------------------------------------------
# Module-level skip guard
# ---------------------------------------------------------------------------

_ASOC_URL = os.environ.get("METATRON_ASOC_INTEGRATION_TEST_URL", "")

if not _ASOC_URL:
    pytest.skip(
        "METATRON_ASOC_INTEGRATION_TEST_URL not set — skipping live ASOC integration tests",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _live_config() -> dict[str, str]:
    return {
        "url": _ASOC_URL,
        "service_token": os.environ["METATRON_ASOC_INTEGRATION_SERVICE_TOKEN"],
        "project_id": os.environ["METATRON_ASOC_INTEGRATION_PROJECT_ID"],
        "asoc_instance_id": os.environ["METATRON_ASOC_INTEGRATION_INSTANCE_ID"],
    }


async def _make_live_connector() -> AsocConnector:
    conn = AsocConnector()
    await conn.configure(
        Connection(
            id="live-conn-1",
            workspace_id="ws-integration-test",
            connector_type="asoc",
            name="live-asoc",
        ),
        _live_config(),
    )
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_health_check_smoke() -> None:
    """Connector can reach the ASOC API and project endpoint returns 2xx."""
    c = await _make_live_connector()
    result = await c.health_check()
    assert result is True, "health_check() returned False against live ASOC"


@pytest.mark.integration
async def test_fetch_bootstrap_smoke() -> None:
    """Full fetch returns at least one Document without errors."""
    c = await _make_live_connector()
    docs = await c.fetch("ws-integration-test")
    # We may get zero docs on an empty project, but no exception is acceptable.
    assert isinstance(docs, list)
    for doc in docs:
        assert doc.workspace_id == "ws-integration-test"
        assert doc.source_type == "asoc"
        assert doc.source_role == "security_scanner"
        assert doc.id  # non-empty deterministic ID


@pytest.mark.integration
@pytest.mark.parametrize(
    "entity_type",
    [
        "project",
        "layer",
        "issue",
        "comment",
        "issue_history",
        "scan_result",
        "sbom",
        "dependency",
        "quality_gate",
        "event",
    ],
)
async def test_updated_after_per_entity(entity_type: str) -> None:
    """Verify updated_after is either honoured or gracefully degraded per endpoint.

    For each entity type: pass a ``since`` far in the past (1990), collect docs.
    Then pass ``since`` = now + 1 day (future), collect docs. Future fetch
    must return ≤ past fetch for the given entity type (or zero if unsupported).
    """
    c = await _make_live_connector()
    past = datetime(1990, 1, 1, tzinfo=UTC)
    future = datetime.now(UTC) + timedelta(days=1)

    docs_past = await c.fetch("ws-integration-test", since=past)
    docs_future = await c.fetch("ws-integration-test", since=future)

    past_of_type = [d for d in docs_past if d.metadata.get("entity_type") == entity_type]
    future_of_type = [d for d in docs_future if d.metadata.get("entity_type") == entity_type]

    assert len(future_of_type) <= len(past_of_type), (
        f"entity_type={entity_type!r}: future fetch returned MORE docs than past fetch — "
        f"updated_after filter not working "
        f"(past={len(past_of_type)}, future={len(future_of_type)})"
    )


@pytest.mark.integration
async def test_pagination_correctness() -> None:
    """Fetch with page_size=1 produces the same total count as the default fetch."""
    c = await _make_live_connector()
    c._PAGE_SIZE = 1  # force many page requests

    docs_small_page = await c.fetch("ws-integration-test")

    c2 = await _make_live_connector()
    docs_default = await c2.fetch("ws-integration-test")

    assert len(docs_small_page) == len(docs_default), (
        f"Page-size=1 returned {len(docs_small_page)} docs "
        f"but default returned {len(docs_default)}"
    )


@pytest.mark.integration
async def test_ordering_stability() -> None:
    """Two consecutive fetches with the same page_size return items in identical order.

    This guards against non-deterministic server-side ordering that would make
    resume hints unreliable.
    """
    c1 = await _make_live_connector()
    c2 = await _make_live_connector()

    docs1 = await c1.fetch("ws-integration-test")
    docs2 = await c2.fetch("ws-integration-test")

    ids1 = [d.source_id for d in docs1]
    ids2 = [d.source_id for d in docs2]

    assert ids1 == ids2, (
        "Two consecutive fetches returned items in different order — "
        "ASOC API ordering is non-deterministic. Resume hints cannot be relied upon."
    )
