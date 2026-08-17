"""Load isolated LoCoMo benchmark configuration without exposing secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCH_ROOT.parents[1]
DEFAULT_ENV_PATH = BENCH_ROOT / ".env.benchmark"
REPO_ENV_PATH = REPO_ROOT / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_dotenv() -> None:
    for key, value in _parse_env_file(REPO_ENV_PATH).items():
        os.environ.setdefault(key, value)
    for key, value in _parse_env_file(DEFAULT_ENV_PATH).items():
        if value:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class BenchConfig:
    metronix_mcp_api_key: str
    metronix_mcp_url: str
    metronix_api_url: str
    workspace_id: str
    chat_api_key: str
    chat_base_url: str
    chat_model: str
    retrieve_top_k: int
    agent_id_prefix: str = "locomo"

    @classmethod
    def from_env(cls) -> BenchConfig:
        load_dotenv()
        return cls(
            metronix_mcp_api_key=os.getenv("METRONIX_MCP_API_KEY", ""),
            metronix_mcp_url=os.getenv("METRONIX_MCP_URL", "http://localhost:8000/mcp"),
            metronix_api_url=os.getenv("METRONIX_API_URL", "http://localhost:8000"),
            workspace_id=os.getenv("LOCOMO_WORKSPACE_ID", "LOCOMO"),
            chat_api_key=os.getenv("LOCOMO_CHAT_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
            chat_base_url=os.getenv("LOCOMO_CHAT_BASE_URL", "https://api.openai.com/v1"),
            chat_model=os.getenv("LOCOMO_CHAT_MODEL", "gpt-4o-mini"),
            retrieve_top_k=int(os.getenv("LOCOMO_RETRIEVE_TOP_K", "10")),
        )

    def missing(self) -> list[str]:
        missing: list[str] = []
        if not self.metronix_mcp_api_key:
            missing.append("METRONIX_MCP_API_KEY")
        if not self.chat_api_key:
            missing.append("LOCOMO_CHAT_API_KEY")
        return missing
