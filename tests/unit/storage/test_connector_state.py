from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from metronix.core.config import Settings
from metronix.storage.pg_connection import get_session
from metronix.storage.pg_models import ConnectionRow
from metronix.storage.postgres import PostgresStore


@pytest.fixture
async def store():
    yield PostgresStore(Settings().postgres_dsn)


@pytest.fixture
def seeded_conn():
    suffix = uuid4().hex[:10]
    ws = f"ws_cs_{suffix}"
    cid = f"conn_cs_{suffix}"
    with get_session() as s:
        s.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :sl)"),
            {"id": ws, "n": "t", "sl": ws},
        )
        s.add(
            ConnectionRow(
                id=cid,
                workspace_id=ws,
                connector_type="gdrive",
                name="T",
                config_encrypted=b"x",
                status="active",
                enabled=True,
            )
        )
    yield cid


async def test_get_returns_none_when_absent(store, seeded_conn):
    assert await store.get_connector_state(seeded_conn) is None


async def test_set_then_get_roundtrips(store, seeded_conn):
    await store.set_connector_state(seeded_conn, {"page_token": "PT1"})
    assert await store.get_connector_state(seeded_conn) == {"page_token": "PT1"}


async def test_set_upserts(store, seeded_conn):
    await store.set_connector_state(seeded_conn, {"page_token": "PT1"})
    await store.set_connector_state(seeded_conn, {"page_token": "PT2"})
    assert await store.get_connector_state(seeded_conn) == {"page_token": "PT2"}
