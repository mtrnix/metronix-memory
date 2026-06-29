"""get_agent_registry_service passes event_bus through to the service."""

from __future__ import annotations

from unittest.mock import MagicMock

from metronix.api.app import create_app
from metronix.api.dependencies import get_agent_registry_service
from metronix.core.config import get_settings


def test_event_bus_passed_into_agent_registry_service() -> None:
    settings = get_settings()
    app = create_app(settings)
    req = MagicMock()
    req.app = app
    req.state = MagicMock()
    req.state.user = {"workspace_ids": ["ws_test"]}
    req.query_params = {}
    req.state._workspace_id_cached = None

    svc = get_agent_registry_service(req)
    # Service must have the bus wired — same instance as the plugin manager's bus
    assert svc._event_bus is app.state.plugin_manager.get_event_bus()


def test_event_bus_reused_across_calls_same_workspace() -> None:
    settings = get_settings()
    app = create_app(settings)
    req = MagicMock()
    req.app = app
    req.state = MagicMock()
    req.state.user = {"workspace_ids": ["ws_test"]}
    req.query_params = {}
    req.state._workspace_id_cached = None

    svc1 = get_agent_registry_service(req)
    svc2 = get_agent_registry_service(req)
    assert svc1 is svc2  # cached on app.state
    assert svc2._event_bus is app.state.plugin_manager.get_event_bus()
