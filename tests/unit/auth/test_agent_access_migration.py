"""Contract checks for the agent-access Alembic migration."""

from __future__ import annotations

import importlib


def test_agent_access_migration_declares_next_revision() -> None:
    migration = importlib.import_module("migrations.versions.032_agent_access_grants")

    assert migration.revision == "032"
    assert migration.down_revision == "031"
