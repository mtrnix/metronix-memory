"""The sync DSN must name its driver explicitly.

A bare ``postgresql://`` URL means "the SQLAlchemy default driver", which is
psycopg2 on SQLAlchemy 2.0 but psycopg (v3) on 2.1. The Docker image resolves
dependencies with pip (not ``uv.lock``), so it can pick up SQLAlchemy 2.1 while
only psycopg2 is installed, and startup migrations fail with
``No module named 'psycopg'``.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url

from metronix.core.config import Settings


def test_sync_dsn_pins_psycopg2_driver() -> None:
    url = make_url(Settings().postgres_sync_dsn)

    assert url.drivername == "postgresql+psycopg2"


def test_sync_dsn_keeps_connection_parts() -> None:
    settings = Settings(
        postgres_user="u",
        postgres_password="p",
        postgres_host="h",
        postgres_port=5433,
        postgres_db="d",
    )
    url = make_url(settings.postgres_sync_dsn)

    assert (url.username, url.password, url.host, url.port, url.database) == (
        "u",
        "p",
        "h",
        5433,
        "d",
    )
