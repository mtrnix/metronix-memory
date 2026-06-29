"""create_app() wires AgentIdContextMiddleware + ActivityLogger conditionally."""

from __future__ import annotations

from metronix.api.app import create_app
from metronix.core.config import Settings
from metronix.core.events import AGENT_CREATED, MEMORY_STORED, TOOL_CALLED


def test_agent_id_middleware_is_registered() -> None:
    app = create_app(Settings())
    names = [m.cls.__name__ for m in app.user_middleware]
    assert "AgentIdContextMiddleware" in names


def test_activity_logger_subscribed_when_enabled() -> None:
    settings = Settings(METRONIX_ACTIVITY_LOG_ENABLED=True)
    app = create_app(settings)
    bus = app.state.plugin_manager.get_event_bus()
    # At least one handler attached for each topic the logger cares about
    assert bus.handler_count(MEMORY_STORED) >= 1
    assert bus.handler_count(TOOL_CALLED) >= 1
    assert bus.handler_count(AGENT_CREATED) >= 1


def test_activity_store_exposed_on_app_state_when_enabled() -> None:
    settings = Settings(METRONIX_ACTIVITY_LOG_ENABLED=True)
    app = create_app(settings)
    assert getattr(app.state, "activity_store", None) is not None
    assert getattr(app.state, "activity_logger", None) is not None


def test_activity_logger_not_subscribed_when_disabled() -> None:
    settings = Settings(METRONIX_ACTIVITY_LOG_ENABLED=False)
    app = create_app(settings)
    bus = app.state.plugin_manager.get_event_bus()
    # No activity-logger handlers — activity topics have zero subscribers
    assert bus.handler_count(TOOL_CALLED) == 0
    assert bus.handler_count(MEMORY_STORED) == 0
    assert bus.handler_count(AGENT_CREATED) == 0


def test_activity_state_absent_when_disabled() -> None:
    settings = Settings(METRONIX_ACTIVITY_LOG_ENABLED=False)
    app = create_app(settings)
    assert getattr(app.state, "activity_store", None) is None
    assert getattr(app.state, "activity_logger", None) is None
