"""Contract checks for expiring delegated agent-access grants."""

from __future__ import annotations

import importlib


def test_agent_access_expiry_migration_extends_the_grant_schema() -> None:
    migration = importlib.import_module("migrations.versions.033_agent_access_grant_expiry")

    assert migration.revision == "033"
    assert migration.down_revision == "032"
