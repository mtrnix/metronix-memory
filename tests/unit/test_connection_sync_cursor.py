from __future__ import annotations

from unittest.mock import AsyncMock

from metronix.connectors.connection_sync import _load_cursor, _persist_cursor
from metronix.core.interfaces import CursorConnector


class _Cursor:
    def __init__(self):
        self.loaded = "unset"
        self._next = "TNEXT"

    def load_cursor(self, cursor):
        self.loaded = cursor

    def take_cursor(self):
        return self._next


def test_cursor_connector_isinstance():
    assert isinstance(_Cursor(), CursorConnector)
    assert not isinstance(object(), CursorConnector)


async def test_load_passes_stored_token():
    store = AsyncMock()
    store.get_connector_state.return_value = {"page_token": "PT"}
    c = _Cursor()
    await _load_cursor(store, "c1", c)
    assert c.loaded == "PT"


async def test_load_degrades_to_none_on_store_error():
    store = AsyncMock()
    store.get_connector_state.side_effect = Exception("db down")
    c = _Cursor()
    await _load_cursor(store, "c1", c)
    assert c.loaded is None  # degrade → full sweep


async def test_load_skips_non_cursor_connector():
    store = AsyncMock()
    await _load_cursor(store, "c1", object())  # no load_cursor attr
    store.get_connector_state.assert_not_called()


async def test_persist_on_success():
    store = AsyncMock()
    await _persist_cursor(store, "c1", _Cursor(), "success")
    store.set_connector_state.assert_awaited_once_with("c1", {"page_token": "TNEXT"})


async def test_no_persist_on_partial():
    store = AsyncMock()
    await _persist_cursor(store, "c1", _Cursor(), "partial")
    store.set_connector_state.assert_not_called()


async def test_no_persist_when_token_none():
    store = AsyncMock()
    c = _Cursor()
    c._next = None
    await _persist_cursor(store, "c1", c, "success")
    store.set_connector_state.assert_not_called()
