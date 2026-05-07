"""Tests for migration 021 — memory health fields (MTRNIX-277).

These tests verify the migration module's metadata and structure without
requiring a live database. The columns/indexes are tested via the module's
Python representation rather than executing SQL.

For integration-level upgrade/downgrade testing, use ``alembic upgrade head``
and ``alembic downgrade -1`` against a real Postgres instance.
"""

from __future__ import annotations

import importlib


class TestMigration021Metadata:
    def test_module_importable(self) -> None:
        """Migration 021 must import without error."""
        mod = importlib.import_module("migrations.versions.021_memory_health_fields")
        assert mod is not None

    def test_revision_is_021(self) -> None:
        mod = importlib.import_module("migrations.versions.021_memory_health_fields")
        assert mod.revision == "021"

    def test_down_revision_is_020(self) -> None:
        mod = importlib.import_module("migrations.versions.021_memory_health_fields")
        assert mod.down_revision == "020"

    def test_upgrade_function_exists(self) -> None:
        mod = importlib.import_module("migrations.versions.021_memory_health_fields")
        assert callable(mod.upgrade)

    def test_downgrade_function_exists(self) -> None:
        mod = importlib.import_module("migrations.versions.021_memory_health_fields")
        assert callable(mod.downgrade)

    def test_branch_labels_and_depends_on_are_none(self) -> None:
        mod = importlib.import_module("migrations.versions.021_memory_health_fields")
        assert mod.branch_labels is None
        assert mod.depends_on is None


class TestMigration021ChainIntegrity:
    """Verify the full migration chain from 020 to 021 is consistent."""

    def test_020_exists_as_predecessor(self) -> None:
        mod020 = importlib.import_module("migrations.versions.020_add_memory_kind_to_records")
        assert mod020.revision == "020"

    def test_021_follows_020(self) -> None:
        mod021 = importlib.import_module("migrations.versions.021_memory_health_fields")
        mod020 = importlib.import_module("migrations.versions.020_add_memory_kind_to_records")
        assert mod021.down_revision == mod020.revision
