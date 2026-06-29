"""ENTITY_WRITE event constant (PROJ-372 P4)."""

from metronix.core.events import ENTITY_WRITE


def test_entity_write_constant() -> None:
    assert ENTITY_WRITE == "entity_write"
