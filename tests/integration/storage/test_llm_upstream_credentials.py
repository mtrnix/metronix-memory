"""LlmUpstreamCredentialsStore roundtrip (MTRNIX-372 P1)."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import Settings
from metronix.storage.llm_upstream_credentials import LlmUpstreamCredentialsStore

pytestmark = pytest.mark.integration


@pytest.fixture
def fernet_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
async def store(fernet_key: str):
    settings = Settings()
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    yield LlmUpstreamCredentialsStore(engine, fernet_key=fernet_key)
    await engine.dispose()


async def test_create_and_resolve(store: LlmUpstreamCredentialsStore) -> None:
    cred_id = await store.create("WS_TEST", "openai", "sk-secret-123")
    assert cred_id
    got = await store.get_decrypted(cred_id, "WS_TEST")
    assert got == "sk-secret-123"


async def test_cross_workspace_isolation(store: LlmUpstreamCredentialsStore) -> None:
    cred_id = await store.create("WS_A", "openai", "sk-a")
    assert await store.get_decrypted(cred_id, "WS_B") is None


async def test_delete(store: LlmUpstreamCredentialsStore) -> None:
    cred_id = await store.create("WS_TEST", "openai", "sk-x")
    assert await store.delete(cred_id, "WS_TEST") is True
    assert await store.get_decrypted(cred_id, "WS_TEST") is None
