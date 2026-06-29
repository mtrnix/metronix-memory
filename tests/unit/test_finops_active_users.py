"""Tests for FinOps active-users helper and endpoint."""

from __future__ import annotations

from collections import namedtuple
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

# Lightweight named tuple to mimic SQLAlchemy aggregate row result
_AggRow = namedtuple("_AggRow", ["active_users", "period_queries"])


class TestFetchActiveUsers:
    """`_fetch_active_users` returns (active_users, period_queries) from llm_generation_log."""

    @staticmethod
    def _mock_session_returning(row):
        """Build a MagicMock session whose execute(...).one() returns `row`."""
        mock_session = MagicMock()
        mock_session.execute.return_value.one.return_value = row
        return mock_session

    @patch("metronix.storage.pg_connection.get_session")
    def test_empty_table_returns_zero_zero(self, mock_get_session):
        """No rows → (0, 0)."""
        from metronix.api.routes.finops import _fetch_active_users

        mock_session = self._mock_session_returning(_AggRow(0, 0))
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        since = datetime.now(UTC) - timedelta(days=30)
        result = _fetch_active_users("ws_test", since)

        assert result == (0, 0)
        assert mock_session.execute.called

    @patch("metronix.storage.pg_connection.get_session")
    def test_single_row_returns_one_one(self, mock_get_session):
        from metronix.api.routes.finops import _fetch_active_users

        mock_session = self._mock_session_returning(_AggRow(1, 1))
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        since = datetime.now(UTC) - timedelta(days=30)
        assert _fetch_active_users("ws_test", since) == (1, 1)

    @patch("metronix.storage.pg_connection.get_session")
    def test_distinct_vs_total(self, mock_get_session):
        """5 rows, 1 user → (1, 5). Confirms helper returns BOTH numbers separately."""
        from metronix.api.routes.finops import _fetch_active_users

        mock_session = self._mock_session_returning(_AggRow(1, 5))
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        since = datetime.now(UTC) - timedelta(days=30)
        assert _fetch_active_users("ws_test", since) == (1, 5)

    @patch("metronix.api.routes.finops.logger")
    @patch("metronix.storage.pg_connection.get_session")
    def test_db_error_returns_zero_zero_and_logs(self, mock_get_session, mock_logger):
        """DB exception → (0, 0); structlog warning emitted; never re-raised."""
        from metronix.api.routes.finops import _fetch_active_users

        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("DB down")
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        since = datetime.now(UTC) - timedelta(days=30)
        result = _fetch_active_users("ws_test", since)

        assert result == (0, 0)
        mock_logger.warning.assert_called_once()
        # event name is the first positional arg of structlog's warning(...)
        event_name = mock_logger.warning.call_args.args[0]
        assert event_name == "finops.active_users.db_error"

    @patch("metronix.storage.pg_connection.get_session")
    def test_query_filters_are_correct(self, mock_get_session):
        """Verify the SQL where-clause has all required filters with the exact
        values: workspace_id, user_id IS NOT NULL, source IN ('oai_compat',
        'rest'), call_site = 'rag_answer', created_at >= since.

        Uses literal_binds=True so the actual filter VALUES render inline —
        otherwise a regression that drops 'rest' from the source tuple or
        renames the call_site would still pass a loose 'source in' substring
        check."""
        from sqlalchemy.dialects import postgresql

        from metronix.api.routes.finops import (
            _RAG_ANSWER_CALL_SITE,
            _USER_FACING_SOURCES,
            _fetch_active_users,
        )

        captured_stmt = {}

        def capture_execute(stmt, *args, **kwargs):
            captured_stmt["stmt"] = stmt
            mock = MagicMock()
            mock.one.return_value = _AggRow(0, 0)
            return mock

        mock_session = MagicMock()
        mock_session.execute.side_effect = capture_execute
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        since = datetime.now(UTC) - timedelta(days=30)
        _fetch_active_users("ws_test", since)

        compiled = str(
            captured_stmt["stmt"].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        assert "llm_generation_log" in compiled
        assert "count(distinct" in compiled  # active_users
        assert "user_id is not null" in compiled
        assert "call_site" in compiled
        assert "created_at" in compiled
        assert "workspace_id" in compiled
        # Exact filter VALUES must be present (catches dropped/renamed filters).
        assert _RAG_ANSWER_CALL_SITE == "rag_answer"
        assert "'rag_answer'" in compiled
        for src in _USER_FACING_SOURCES:
            assert f"'{src}'" in compiled, f"source filter missing {src!r}"


class TestActiveUsersEndpoint:
    """`get_active_users` HTTP endpoint behaviour."""

    @patch("metronix.api.routes.finops._fetch_active_users")
    async def test_response_shape_and_period_echo(self, mock_fetch):
        """Response contains period_days (echoed), active_users, period_queries."""
        from metronix.api.routes.finops import get_active_users

        mock_fetch.return_value = (42, 1337)

        resp = await get_active_users(workspace_id="ws_test", days=30)

        assert resp.period_days == 30
        assert resp.active_users == 42
        assert resp.period_queries == 1337

    @patch("metronix.api.routes.finops._fetch_active_users")
    async def test_days_parameter_passed_to_helper(self, mock_fetch):
        """`days=7` produces a `since` ~7 days in the past, ±1 minute."""
        from metronix.api.routes.finops import get_active_users

        mock_fetch.return_value = (0, 0)

        before = datetime.now(UTC)
        await get_active_users(workspace_id="ws_test", days=7)
        after = datetime.now(UTC)

        args, _ = mock_fetch.call_args
        workspace_id_arg, since_arg = args
        assert workspace_id_arg == "ws_test"

        expected_since_low = before - timedelta(days=7)
        expected_since_high = after - timedelta(days=7)
        assert expected_since_low <= since_arg <= expected_since_high

    @patch("metronix.api.routes.finops._fetch_active_users")
    async def test_zero_values_passthrough(self, mock_fetch):
        """Helper returning (0, 0) must come through as 0/0, not omitted."""
        from metronix.api.routes.finops import get_active_users

        mock_fetch.return_value = (0, 0)

        resp = await get_active_users(workspace_id="ws_test", days=30)

        assert resp.period_days == 30
        assert resp.active_users == 0
        assert resp.period_queries == 0


class TestActiveUsersHttpRoute:
    """End-to-end route test via FastAPI TestClient — verifies route is mounted
    and parameter validation (days range 1..365) is enforced by FastAPI."""

    @patch("metronix.api.routes.finops._fetch_active_users")
    def test_route_returns_200_with_expected_json(self, mock_fetch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from metronix.api.routes.finops import router

        mock_fetch.return_value = (5, 100)

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        client = TestClient(app)
        r = client.get("/api/v1/finops/active-users?workspace_id=ws_test&days=14")

        assert r.status_code == 200
        body = r.json()
        assert body == {"period_days": 14, "active_users": 5, "period_queries": 100}

    @patch("metronix.api.routes.finops._fetch_active_users")
    def test_route_default_days_is_30(self, mock_fetch):
        """Calling without days yields period_days=30 in the response."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from metronix.api.routes.finops import router

        mock_fetch.return_value = (0, 0)

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        client = TestClient(app)
        r = client.get("/api/v1/finops/active-users?workspace_id=ws_test")

        assert r.status_code == 200
        assert r.json()["period_days"] == 30

    def test_route_rejects_days_below_one(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from metronix.api.routes.finops import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        client = TestClient(app)
        r = client.get("/api/v1/finops/active-users?workspace_id=ws_test&days=0")

        assert r.status_code == 422

    def test_route_rejects_days_above_365(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from metronix.api.routes.finops import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        client = TestClient(app)
        r = client.get("/api/v1/finops/active-users?workspace_id=ws_test&days=999")

        assert r.status_code == 422

    def test_route_requires_workspace_id(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from metronix.api.routes.finops import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        client = TestClient(app)
        r = client.get("/api/v1/finops/active-users")

        assert r.status_code == 422
