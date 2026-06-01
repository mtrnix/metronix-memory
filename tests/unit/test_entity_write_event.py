"""ENTITY_WRITE event constant (MTRNIX-372 P4)."""

from metatron.core.events import ENTITY_WRITE


def test_entity_write_constant() -> None:
    assert ENTITY_WRITE == "entity_write"
