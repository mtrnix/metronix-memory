from __future__ import annotations

import sys
import types
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


if "agent.memory_provider" not in sys.modules:
    agent_pkg = sys.modules.setdefault("agent", types.ModuleType("agent"))
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        """Minimal Hermes ABC stub for local plugin tests."""

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent.memory_provider"] = memory_provider_mod
    setattr(agent_pkg, "memory_provider", memory_provider_mod)

