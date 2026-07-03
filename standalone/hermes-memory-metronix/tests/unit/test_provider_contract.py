from __future__ import annotations

from types import SimpleNamespace

from metronix import MetronixMemoryProvider, register


def test_provider_name():
    provider = MetronixMemoryProvider()
    assert provider.name == "metronix"


def test_get_tool_schemas_is_empty():
    provider = MetronixMemoryProvider()
    assert provider.get_tool_schemas() == []


def test_system_prompt_block_is_stable():
    provider = MetronixMemoryProvider()
    block = provider.system_prompt_block()
    assert "Metronix Memory" in block
    assert "background context" in block


def test_register_calls_memory_provider_hook():
    calls: list[object] = []

    ctx = SimpleNamespace(register_memory_provider=lambda provider: calls.append(provider))

    register(ctx)

    assert len(calls) == 1
    assert isinstance(calls[0], MetronixMemoryProvider)

