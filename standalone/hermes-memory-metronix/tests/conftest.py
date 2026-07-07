from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


HERMES_AGENT_SRC = os.environ.get("HERMES_AGENT_SRC", "")
_hermes_agent_path = Path(HERMES_AGENT_SRC) if HERMES_AGENT_SRC else None
_real_memory_provider_file = (
    _hermes_agent_path / "agent" / "memory_provider.py" if _hermes_agent_path else None
)
HAS_REAL_HERMES_AGENT = bool(_real_memory_provider_file and _real_memory_provider_file.is_file())


def _load_real_memory_provider_abc(hermes_agent_src: Path) -> None:
    """Register the REAL agent.memory_provider module in sys.modules.

    Loads agent/memory_provider.py directly by file path, without executing
    the real agent/__init__.py -- that package imports jiter_preload, a
    hermes-agent runtime dependency not installed in this plugin's own
    environment. agent/memory_provider.py itself only imports stdlib, so
    loading it standalone is safe.
    """
    if "agent" not in sys.modules:
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = [str(hermes_agent_src / "agent")]
        sys.modules["agent"] = agent_pkg

    spec = importlib.util.spec_from_file_location(
        "agent.memory_provider", str(hermes_agent_src / "agent" / "memory_provider.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent.memory_provider"] = module
    spec.loader.exec_module(module)
    setattr(sys.modules["agent"], "memory_provider", module)


if HAS_REAL_HERMES_AGENT:
    if str(_hermes_agent_path) not in sys.path:
        sys.path.insert(0, str(_hermes_agent_path))
    if "agent.memory_provider" not in sys.modules:
        _load_real_memory_provider_abc(_hermes_agent_path)
elif "agent.memory_provider" not in sys.modules:
    agent_pkg = sys.modules.setdefault("agent", types.ModuleType("agent"))
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        """Minimal Hermes ABC stub for local plugin tests."""

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent.memory_provider"] = memory_provider_mod
    setattr(agent_pkg, "memory_provider", memory_provider_mod)
