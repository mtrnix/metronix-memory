"""Regression for B2 — get_memory_service must wire event_bus from plugin_manager.

Symmetric to test_dependencies_agent_registry.py. Without this, REST/MCP memory
operations silently no-op on the activity log.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from metronix.api.app import create_app
from metronix.api.dependencies import get_memory_service
from metronix.core.config import get_settings


def test_event_bus_passed_into_memory_service() -> None:
    settings = get_settings()
    app = create_app(settings)
    req = MagicMock()
    req.app = app
    req.state = MagicMock()
    req.state.user = {"workspace_ids": ["ws_test"]}
    req.query_params = {}
    req.state._workspace_id_cached = None

    svc = get_memory_service(req)
    assert svc._event_bus is app.state.plugin_manager.get_event_bus()
