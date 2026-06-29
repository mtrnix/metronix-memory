"""WorkspaceEntityTrie (PROJ-372 P4)."""

from metronix.core.config import Settings
from metronix.proxy.entity_trie import WorkspaceEntityTrie


async def test_match_substring_casefold() -> None:
    async def _fetch(ws: str) -> list[str]:
        return ["Acme Corp", "Bob"]

    t = WorkspaceEntityTrie(settings=Settings(), fetch_entities=_fetch, clock=lambda: 100.0)
    matched = await t.match("we met bob at ACME CORP yesterday", "WS")
    assert set(matched) == {"Acme Corp", "Bob"}


async def test_no_match() -> None:
    async def _fetch(ws: str) -> list[str]:
        return ["Acme"]

    t = WorkspaceEntityTrie(settings=Settings(), fetch_entities=_fetch, clock=lambda: 1.0)
    assert await t.match("nothing here", "WS") == []


async def test_ttl_rebuild() -> None:
    calls = {"n": 0}

    async def _fetch(ws: str) -> list[str]:
        calls["n"] += 1
        return ["Acme"]

    now = {"t": 0.0}
    t = WorkspaceEntityTrie(
        settings=Settings(METRONIX_PROXY_ENTITY_TRIE_TTL_SECONDS=10),
        fetch_entities=_fetch,
        clock=lambda: now["t"],
    )
    await t.match("acme", "WS")
    await t.match("acme", "WS")
    assert calls["n"] == 1  # cached
    now["t"] = 20.0
    await t.match("acme", "WS")
    assert calls["n"] == 2  # rebuilt after TTL


async def test_invalidate() -> None:
    calls = {"n": 0}

    async def _fetch(ws: str) -> list[str]:
        calls["n"] += 1
        return ["Acme"]

    t = WorkspaceEntityTrie(settings=Settings(), fetch_entities=_fetch, clock=lambda: 5.0)
    await t.match("acme", "WS")
    t.invalidate("WS")
    await t.match("acme", "WS")
    assert calls["n"] == 2
