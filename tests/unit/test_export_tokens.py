import pytest

from metronix.export.tokens import ExportTokenStore


class FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}

    async def set(self, key, value, ttl=None):
        self.kv[key] = value if isinstance(value, str) else value.decode()

    async def get(self, key):
        return self.kv.get(key)

    async def getdel(self, key):
        return self.kv.pop(key, None)


@pytest.mark.asyncio
async def test_mint_then_consume_is_one_time():
    store = ExportTokenStore(FakeRedis(), ttl_seconds=60)
    token = await store.mint("exp1", "/data/exports/exp1.zip")
    assert len(token) >= 22  # token_urlsafe(32) ~ 43 chars
    first = await store.consume(token)
    assert first == {"export_id": "exp1", "path": "/data/exports/exp1.zip"}
    assert await store.consume(token) is None  # consumed (atomic getdel)


@pytest.mark.asyncio
async def test_peek_is_non_destructive():
    store = ExportTokenStore(FakeRedis(), ttl_seconds=60)
    token = await store.mint("exp1", "/p/exp1.zip")
    assert await store.peek(token) == {"export_id": "exp1", "path": "/p/exp1.zip"}
    # peek did not consume; consume still works once
    assert await store.consume(token) is not None
    assert await store.peek(token) is None


@pytest.mark.asyncio
async def test_consume_unknown_token():
    store = ExportTokenStore(FakeRedis(), ttl_seconds=60)
    assert await store.consume("nope") is None
