"""Tests for /admin/reindex — PG cursor reset (MTRNIX-332)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text

from metronix.api.routes.admin import trigger_reindex
from metronix.storage.pg_connection import get_session
from metronix.storage.pg_models import ConnectionRow


@pytest.fixture
def seeded_connection_with_cursor() -> tuple[str, str, datetime]:
    """Seed a workspace + connection with a non-NULL last_synced_at."""
    suffix = uuid4().hex[:10]
    ws = f"ws_reidx_{suffix}"
    cid = f"conn_reidx_{suffix}"
    cursor = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    with get_session() as s:
        s.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :sl)"),
            {"id": ws, "n": "t", "sl": ws},
        )
        s.add(
            ConnectionRow(
                id=cid,
                workspace_id=ws,
                connector_type="jira",
                name="T",
                config_encrypted=b"x",
                status="active",
                enabled=True,
                last_synced_at=cursor,
            )
        )
    return ws, cid, cursor


def _make_request_with_app_state() -> MagicMock:
    """Build a minimal Request-like with app.state.settings (post-S1 refactor)."""
    from metronix.core.config import Settings

    request = MagicMock()
    request.app.state.settings = Settings()
    # No pre-existing pooled store → route lazily creates one.
    request.app.state.postgres = None
    return request


async def test_reindex_clears_last_synced_at(seeded_connection_with_cursor) -> None:
    """After /reindex, connections.last_synced_at MUST be NULL.

    Without this, the next sync would still use the old cursor and skip
    documents that the reindex is meant to re-ingest from scratch.
    """
    ws, cid, prior_cursor = seeded_connection_with_cursor

    # Sanity: cursor was set
    with get_session() as s:
        assert s.query(ConnectionRow).filter_by(id=cid).first().last_synced_at == prior_cursor

    # Mock Neo4j away — reindex's section 2 (graph clear) requires a live driver
    # that we don't want to touch from this test.
    fake_driver = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)
    fake_driver.session.return_value = fake_session

    request = _make_request_with_app_state()
    with patch("metronix.storage.neo4j_graph.get_graph_driver", return_value=fake_driver):
        resp = await trigger_reindex(request=request, x_confirm_reindex="yes")

    assert resp.sync_state_cleared is True
    with get_session() as s:
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
        assert conn.last_synced_at is None, (
            f"reindex must NULL last_synced_at, still {conn.last_synced_at!r}"
        )


async def test_reindex_requires_confirmation_header() -> None:
    """Without X-Confirm-Reindex: yes, the endpoint must refuse (400)."""
    from fastapi import HTTPException

    request = _make_request_with_app_state()
    with pytest.raises(HTTPException) as exc:
        await trigger_reindex(request=request, x_confirm_reindex=None)
    assert exc.value.status_code == 400
