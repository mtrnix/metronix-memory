"""AssembledContext new fields (PROJ-372 P2)."""

from metronix.core.models import AssembledContext


def test_new_fields_have_safe_defaults() -> None:
    ctx = AssembledContext(system_prompt="x")
    assert ctx.sections == {}
    assert ctx.knowledge_count == 0
    assert ctx.degraded_sections == []
    assert ctx.per_stage_ms == {}
    assert ctx.correlation_id == ""


def test_back_compat_fields_still_present() -> None:
    ctx = AssembledContext(system_prompt="x", preferences_count=2, memories_count=3)
    assert ctx.preferences_count == 2
    assert ctx.memories_count == 3
    assert ctx.tokens_budget == {}
