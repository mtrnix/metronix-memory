"""ProxyActivityLogger (MTRNIX-372 P3)."""

from unittest.mock import AsyncMock

from metronix.proxy.activity import ProxyActivityLogger


async def test_log_writes_row_with_correlation() -> None:
    store = AsyncMock()
    logger = ProxyActivityLogger(store=store, workspace_id="WS")
    await logger.log(
        agent_id="A",
        event_type="proxy.request.received",
        correlation_id="c1",
        data={"model_requested": "gpt-4o-mini"},
    )
    row = store.insert.await_args.args[0]
    assert row.workspace_id == "WS"
    assert row.agent_id == "A"
    assert row.event_type == "proxy.request.received"
    assert row.correlation_id == "c1"
    assert row.event_data == {"model_requested": "gpt-4o-mini"}


async def test_log_swallows_store_errors() -> None:
    store = AsyncMock()
    store.insert.side_effect = RuntimeError("db down")
    logger = ProxyActivityLogger(store=store, workspace_id="WS")
    # must not raise
    await logger.log(agent_id="A", event_type="proxy.upstream.error", correlation_id="c", data={})


async def test_log_noop_when_store_none() -> None:
    logger = ProxyActivityLogger(store=None, workspace_id="WS")
    await logger.log(agent_id="A", event_type="x", correlation_id="c", data={})
