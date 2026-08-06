"""_wrap_tool_with_activity emits TOOL_CALLED + ERROR_OCCURRED."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from metronix.activity.context import bind_agent_id, current_agent_id
from metronix.core import events as evt
from metronix.core.events import EventBus
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal
from metronix.mcp.server import _wrap_tool_with_activity


@pytest.fixture
def bus_spy() -> tuple[EventBus, list[tuple[str, dict[str, object]]]]:
    bus = EventBus()
    calls: list[tuple[str, dict[str, object]]] = []

    async def cap(n: str, p: dict[str, object]) -> None:
        calls.append((n, p))

    bus.subscribe(evt.TOOL_CALLED, cap)
    bus.subscribe(evt.ERROR_OCCURRED, cap)
    return bus, calls


async def test_successful_tool_emits_tool_called(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    bus, calls = bus_spy

    async def my_tool(*, agent_id: str, workspace_id: str) -> str:
        return "ok"

    wrapped = _wrap_tool_with_activity("my_tool", my_tool, bus_getter=lambda: bus)
    out = await wrapped(agent_id="ag_1", workspace_id="ws")

    assert out == "ok"
    names = [n for n, _ in calls]
    assert evt.TOOL_CALLED in names
    assert evt.ERROR_OCCURRED not in names

    payload = next(p for n, p in calls if n == evt.TOOL_CALLED)
    assert payload["tool_name"] == "my_tool"
    assert payload["success"] is True
    assert payload["agent_id"] == "ag_1"
    assert payload["workspace_id"] == "ws"
    assert payload["arguments_truncated"] is False
    assert "agent_id" in payload["arguments"]  # type: ignore[operator]
    assert payload["error_message"] is None


async def test_oversize_arguments_are_truncated(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    bus, calls = bus_spy

    async def big_tool(*, agent_id: str, content: str) -> str:
        return "ok"

    wrapped = _wrap_tool_with_activity("big_tool", big_tool, bus_getter=lambda: bus)
    big_content = "x" * 9000  # > 8 KiB
    await wrapped(agent_id="ag", content=big_content)

    payload = next(p for n, p in calls if n == evt.TOOL_CALLED)
    args = payload["arguments"]
    assert payload["arguments_truncated"] is True
    assert isinstance(args, dict)
    assert args.get("__truncated__") is True
    assert "preview" in args
    assert len(str(args["preview"])) <= 256


async def test_raising_tool_emits_error_and_reraises(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    bus, calls = bus_spy

    async def bad(*, agent_id: str) -> None:
        raise RuntimeError("boom")

    wrapped = _wrap_tool_with_activity("bad", bad, bus_getter=lambda: bus)
    with pytest.raises(RuntimeError):
        await wrapped(agent_id="ag")

    names = [n for n, _ in calls]
    assert evt.TOOL_CALLED in names
    assert evt.ERROR_OCCURRED in names

    tool_evt = next(p for n, p in calls if n == evt.TOOL_CALLED)
    assert tool_evt["success"] is False
    assert tool_evt["error_message"] == "boom"

    err_evt = next(p for n, p in calls if n == evt.ERROR_OCCURRED)
    assert err_evt["error_type"] == "RuntimeError"
    assert err_evt["source"] == "tool"
    ctx = err_evt["context"]
    assert isinstance(ctx, dict)
    assert ctx["tool_name"] == "bad"


async def test_noop_without_bus() -> None:
    async def ok_tool(*, agent_id: str) -> str:
        return "ok"

    wrapped = _wrap_tool_with_activity("ok_tool", ok_tool, bus_getter=lambda: None)
    out = await wrapped(agent_id="ag")
    assert out == "ok"


async def test_noop_without_agent_id(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    bus, calls = bus_spy

    async def ok_tool(*, workspace_id: str) -> str:
        return "ok"

    wrapped = _wrap_tool_with_activity("ok_tool", ok_tool, bus_getter=lambda: bus)
    await wrapped(workspace_id="ws")
    assert [n for n, _ in calls] == []


async def test_bus_getter_resolved_lazily(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    """Regression for B1 closure-capture bug — set_activity_bus_getter
    must take effect even when called AFTER tools were decorated."""
    from metronix.mcp import server as mcp_server

    bus, calls = bus_spy

    async def my_tool(*, agent_id: str) -> str:
        return "ok"

    # Wrap before any bus is set — mirrors the import-time decoration of real
    # MCP tools, when _ACTIVITY_BUS_GETTER is still the no-op default.
    wrapped = _wrap_tool_with_activity(
        "my_tool",
        my_tool,
        bus_getter=lambda: mcp_server._ACTIVITY_BUS_GETTER(),
    )

    # Now install the real bus, mimicking create_app()'s late wiring.
    mcp_server.set_activity_bus_getter(lambda: bus)
    try:
        await wrapped(agent_id="ag_1")
    finally:
        mcp_server.set_activity_bus_getter(lambda: None)

    tool_called = [p for n, p in calls if n == evt.TOOL_CALLED]
    assert len(tool_called) == 1, "lazy resolution should pick up the bus"
    assert tool_called[0]["tool_name"] == "my_tool"


async def test_wrapper_binds_agent_id_to_contextvar(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    """Regression for I3 — agent_id from kwargs must populate the contextvar
    BEFORE the handler runs so downstream code reads the same value."""
    from metronix.activity.context import current_agent_id

    bus, _ = bus_spy
    captured: list[str | None] = []

    async def my_tool(*, agent_id: str) -> str:
        captured.append(current_agent_id.get())
        return "ok"

    wrapped = _wrap_tool_with_activity("my_tool", my_tool, bus_getter=lambda: bus)

    assert current_agent_id.get() is None
    await wrapped(agent_id="ag_42")
    assert captured == ["ag_42"]  # contextvar visible inside handler
    assert current_agent_id.get() is None  # reset on exit


async def test_activity_uses_server_resolved_context_not_raw_tool_arguments(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metronix.mcp import server as mcp_server

    bus, calls = bus_spy
    telemetry_contexts: list[dict[str, object]] = []

    @contextmanager
    def capture_telemetry(**context):
        telemetry_contexts.append(context)
        yield

    monkeypatch.setattr(mcp_server, "set_telemetry_context", capture_telemetry)

    async def my_tool(*, agent_id: str, workspace_id: str) -> str:
        assert current_agent_id.get() == "transport-agent"
        return "ok"

    wrapped = _wrap_tool_with_activity("my_tool", my_tool, bus_getter=lambda: bus)
    principal_token = bind_principal(MCPPrincipal("u1", "viewer", ("ws-a",)))
    agent_token = bind_agent_id("transport-agent")
    try:
        await wrapped(agent_id="raw-target-agent", workspace_id="  ws-a  ")
    finally:
        current_agent_id.reset(agent_token)
        reset_principal(principal_token)

    payload = next(p for n, p in calls if n == evt.TOOL_CALLED)
    assert payload["workspace_id"] == "ws-a"
    assert payload["agent_id"] == "transport-agent"
    assert telemetry_contexts[0]["workspace_id"] == "ws-a"
    assert telemetry_contexts[0]["agent_id"] == "transport-agent"


async def test_denied_workspace_does_not_emit_tenant_scoped_activity(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    bus, calls = bus_spy

    async def denied_tool(*, agent_id: str, workspace_id: str) -> dict[str, object]:
        return {"error": {"code": "FORBIDDEN", "message": "workspace denied"}}

    wrapped = _wrap_tool_with_activity("denied", denied_tool, bus_getter=lambda: bus)
    principal_token = bind_principal(MCPPrincipal("u1", "viewer", ("ws-a",)))
    agent_token = bind_agent_id("transport-agent")
    try:
        result = await wrapped(agent_id="raw-target-agent", workspace_id="ws-denied")
    finally:
        current_agent_id.reset(agent_token)
        reset_principal(principal_token)

    assert "error" in result
    assert calls == []


async def test_tool_error_result_emits_failed_activity(
    bus_spy: tuple[EventBus, list[tuple[str, dict[str, object]]]],
) -> None:
    bus, calls = bus_spy

    async def failing_tool(*, workspace_id: str) -> dict[str, object]:
        return {"error": {"code": "BACKEND_ERROR", "message": "database unavailable"}}

    wrapped = _wrap_tool_with_activity("failing", failing_tool, bus_getter=lambda: bus)
    principal_token = bind_principal(MCPPrincipal("u1", "viewer", ("ws-a",)))
    agent_token = bind_agent_id("transport-agent")
    try:
        result = await wrapped(workspace_id="ws-a")
    finally:
        current_agent_id.reset(agent_token)
        reset_principal(principal_token)

    assert "error" in result
    tool_event = next(p for n, p in calls if n == evt.TOOL_CALLED)
    assert tool_event["success"] is False
    assert tool_event["error_message"] == "database unavailable"
    error_event = next(p for n, p in calls if n == evt.ERROR_OCCURRED)
    assert error_event["error_type"] == "BACKEND_ERROR"
    assert error_event["error_message"] == "database unavailable"
