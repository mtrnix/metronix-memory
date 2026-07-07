from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

PLUGIN_METRONIX_DIR = Path(__file__).resolve().parents[2] / "plugin" / "metronix"
HERMES_AGENT_SRC = os.environ.get("HERMES_AGENT_SRC", "")

pytestmark = pytest.mark.skipif(
    not Path(HERMES_AGENT_SRC, "agent", "memory_provider.py").is_file(),
    reason=f"HERMES_AGENT_SRC checkout not found at {HERMES_AGENT_SRC!r}",
)


def test_provider_is_real_memory_provider_subclass():
    from agent.memory_provider import MemoryProvider
    from metronix import MetronixMemoryProvider

    assert issubclass(MetronixMemoryProvider, MemoryProvider)
    assert isinstance(MetronixMemoryProvider(), MemoryProvider)


def test_plugin_loads_via_real_hermes_loader():
    if HERMES_AGENT_SRC not in sys.path:
        sys.path.insert(0, HERMES_AGENT_SRC)
    plugins_memory = importlib.import_module("plugins.memory")

    provider = plugins_memory._load_provider_from_dir(PLUGIN_METRONIX_DIR)

    assert provider is not None
    assert provider.name == "metronix"
