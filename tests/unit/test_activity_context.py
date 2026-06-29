"""ContextVar holds agent_id for the duration of a request scope."""

import asyncio

from metronix.activity.context import bind_agent_id, current_agent_id


async def test_bind_and_read() -> None:
    assert current_agent_id.get() is None
    token = bind_agent_id("ag_123")
    try:
        assert current_agent_id.get() == "ag_123"
    finally:
        current_agent_id.reset(token)
    assert current_agent_id.get() is None


def test_isolation_between_tasks() -> None:
    async def task(value: str) -> str:
        token = bind_agent_id(value)
        try:
            await asyncio.sleep(0)
            return current_agent_id.get() or ""
        finally:
            current_agent_id.reset(token)

    async def run_parallel() -> tuple[str, str]:
        a, b = await asyncio.gather(task("A"), task("B"))
        return a, b

    a, b = asyncio.run(run_parallel())
    assert a == "A"
    assert b == "B"
    assert current_agent_id.get() is None
