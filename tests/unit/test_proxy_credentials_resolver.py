"""UpstreamCredentialsResolver (MTRNIX-372 P1)."""

from unittest.mock import AsyncMock

from metatron.proxy.credentials import UpstreamCredentialsResolver


async def test_uses_stored_key_when_ref_present() -> None:
    store = AsyncMock()
    store.get_decrypted.return_value = "sk-stored"
    resolver = UpstreamCredentialsResolver(store, default_key="sk-env")
    got = await resolver.resolve("ref-1", "WS")
    assert got == "sk-stored"
    store.get_decrypted.assert_awaited_once_with("ref-1", "WS")


async def test_falls_back_to_env_when_ref_none() -> None:
    store = AsyncMock()
    resolver = UpstreamCredentialsResolver(store, default_key="sk-env")
    got = await resolver.resolve(None, "WS")
    assert got == "sk-env"
    store.get_decrypted.assert_not_called()


async def test_falls_back_to_env_when_ref_missing_in_db() -> None:
    store = AsyncMock()
    store.get_decrypted.return_value = None
    resolver = UpstreamCredentialsResolver(store, default_key="sk-env")
    got = await resolver.resolve("ref-x", "WS")
    assert got == "sk-env"


async def test_returns_empty_when_nothing_available() -> None:
    store = AsyncMock()
    resolver = UpstreamCredentialsResolver(store, default_key="")
    assert await resolver.resolve(None, "WS") == ""
