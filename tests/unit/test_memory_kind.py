"""Unit tests for MemoryKind enum, AssembledContext, and kind field on MemoryRecord."""

from __future__ import annotations

from metatron.core.config import Settings
from metatron.core.models import AssembledContext, MemoryKind, MemoryRecord


class TestMemoryKind:
    """Tests for the MemoryKind StrEnum."""

    def test_values(self) -> None:
        assert MemoryKind.FACT == "fact"
        assert MemoryKind.PREFERENCE == "preference"
        assert MemoryKind.PINNED == "pinned"

    def test_from_string(self) -> None:
        assert MemoryKind("fact") is MemoryKind.FACT
        assert MemoryKind("preference") is MemoryKind.PREFERENCE
        assert MemoryKind("pinned") is MemoryKind.PINNED

    def test_invalid_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            MemoryKind("unknown")

    def test_str_comparison(self) -> None:
        """StrEnum members compare equal to their string values."""
        assert MemoryKind.FACT == "fact"
        assert MemoryKind.PREFERENCE == "preference"
        assert MemoryKind.PINNED == "pinned"


class TestMemoryRecordKind:
    """Tests for kind field on MemoryRecord dataclass."""

    def test_default_kind_is_fact(self) -> None:
        record = MemoryRecord(content="test")
        assert record.kind == MemoryKind.FACT

    def test_set_kind_on_construction(self) -> None:
        record = MemoryRecord(content="test", kind=MemoryKind.PREFERENCE)
        assert record.kind == MemoryKind.PREFERENCE

    def test_set_kind_after_construction(self) -> None:
        record = MemoryRecord(content="test")
        record.kind = MemoryKind.PINNED
        assert record.kind == MemoryKind.PINNED

    def test_kind_survives_copy(self) -> None:
        from copy import copy

        original = MemoryRecord(content="test", kind=MemoryKind.PREFERENCE)
        cloned = copy(original)
        assert cloned.kind == MemoryKind.PREFERENCE


class TestAssembledContext:
    """Tests for the AssembledContext dataclass."""

    def test_defaults(self) -> None:
        ctx = AssembledContext(system_prompt="hello")
        assert ctx.system_prompt == "hello"
        assert ctx.preferences_count == 0
        assert ctx.memories_count == 0
        assert ctx.tokens_budget == {}

    def test_with_counts(self) -> None:
        ctx = AssembledContext(
            system_prompt="<preferences>\np1\n</preferences>",
            preferences_count=1,
            memories_count=5,
            tokens_budget={"preferences": 100, "memories": 500},
        )
        assert ctx.preferences_count == 1
        assert ctx.memories_count == 5
        assert ctx.tokens_budget == {"preferences": 100, "memories": 500}


class TestMemoryInjectionConfig:
    """Tests for the 4 METATRON_MEMORY_INJECTION_* config vars."""

    def test_defaults(self) -> None:
        s = Settings()
        assert s.memory_injection_enabled is False
        assert s.memory_injection_facts_top_k == 10
        assert s.memory_injection_preferences_budget_tokens == 2000
        assert s.memory_injection_facts_budget_tokens == 3000

    def test_env_override(self) -> None:
        import os

        env = {
            "METATRON_MEMORY_INJECTION_ENABLED": "true",
            "METATRON_MEMORY_INJECTION_FACTS_TOP_K": "20",
            "METATRON_MEMORY_INJECTION_PREFERENCES_BUDGET_TOKENS": "4000",
            "METATRON_MEMORY_INJECTION_FACTS_BUDGET_TOKENS": "6000",
        }
        original = {k: os.environ.pop(k, None) for k in env}
        try:
            os.environ.update(env)
            s = Settings()
            assert s.memory_injection_enabled is True
            assert s.memory_injection_facts_top_k == 20
            assert s.memory_injection_preferences_budget_tokens == 4000
            assert s.memory_injection_facts_budget_tokens == 6000
        finally:
            for k, v in original.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
