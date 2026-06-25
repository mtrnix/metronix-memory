"""Load LongMemEval benchmark environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BENCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCH_ROOT.parents[1]
BENCHMARK_ENV_FILE = ".env.benchmark"
LEGACY_BENCHMARK_ENV_FILE = ".env"
DEFAULT_ENV_PATH = BENCH_ROOT / BENCHMARK_ENV_FILE
LEGACY_ENV_PATH = BENCH_ROOT / LEGACY_BENCHMARK_ENV_FILE
REPO_ENV_PATH = REPO_ROOT / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_dotenv(path: Path | None = None) -> None:
    """Load env files into os.environ.

    Repo-root `.env` fills missing Metronix install values.
    `benchmarks/longmemeval/.env.benchmark` overrides benchmark settings
    (any non-empty value wins over existing os.environ entries).
    """
    benchmark_path = path or DEFAULT_ENV_PATH
    if not benchmark_path.exists() and LEGACY_ENV_PATH.exists():
        benchmark_path = LEGACY_ENV_PATH

    for key, value in _parse_env_file(REPO_ENV_PATH).items():
        os.environ.setdefault(key, value)

    for key, value in _parse_env_file(benchmark_path).items():
        if value:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)


def resolved_env_path() -> Path | None:
    """Return the benchmark env file that load_dotenv reads."""
    if DEFAULT_ENV_PATH.exists():
        return DEFAULT_ENV_PATH
    if LEGACY_ENV_PATH.exists():
        return LEGACY_ENV_PATH
    return None


def _looks_like_api_key(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    return value.startswith(("sk-", "gsk_", "xai-", "Bearer "))


def validate_judge_env(config: "BenchConfig") -> list[str]:
    """Return human-readable config errors for common .env.benchmark mistakes."""
    errors: list[str] = []
    env_path = resolved_env_path()
    path_hint = str(env_path) if env_path else str(DEFAULT_ENV_PATH)

    if config.judge_api_key and not _looks_like_api_key(config.judge_api_key):
        errors.append(
            "LME_JUDGE_API_KEY does not look like an API key "
            f"(got {config.judge_api_key!r}). "
            f"Put your sk-... key in {path_hint}, not the model name."
        )
    if (
        config.judge_model in {"gpt-4o", "gpt-4o-mini"}
        and config.judge_base_url.rstrip("/") == "https://api.openai.com/v1"
        and config.chat_base_url.rstrip("/") != "https://api.openai.com/v1"
    ):
        errors.append(
            "Judge still uses OpenAI defaults (gpt-4o @ api.openai.com) while chat "
            f"uses another provider. Update LME_JUDGE_* in {path_hint} and save the file."
        )
    return errors


def _first(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


@dataclass(frozen=True)
class BenchConfig:
    metronix_mcp_api_key: str
    metronix_mcp_url: str
    metronix_api_url: str
    workspace_id: str
    chat_api_key: str
    chat_base_url: str
    chat_model: str
    judge_api_key: str
    judge_base_url: str
    judge_model: str
    retrieve_top_k: int
    agent_id_prefix: str = "lme"

    @classmethod
    def from_env(cls, *, load_files: bool = True) -> BenchConfig:
        if load_files:
            load_dotenv()
        chat_key = _first(
            os.getenv("LME_CHAT_API_KEY"),
            os.getenv("OPENAI_API_KEY"),
        )
        judge_key = _first(
            os.getenv("LME_JUDGE_API_KEY"),
            os.getenv("LME_CHAT_API_KEY"),
            os.getenv("OPENAI_API_KEY"),
        )
        return cls(
            metronix_mcp_api_key=os.getenv("METRONIX_MCP_API_KEY", ""),
            metronix_mcp_url=os.getenv("METRONIX_MCP_URL", "http://localhost:8000/mcp"),
            metronix_api_url=os.getenv("METRONIX_API_URL", "http://localhost:8000"),
            workspace_id=os.getenv("LME_WORKSPACE_ID", "MABENCH"),
            chat_api_key=chat_key or "",
            chat_base_url=os.getenv("LME_CHAT_BASE_URL", "https://api.openai.com/v1"),
            chat_model=os.getenv("LME_CHAT_MODEL", "gpt-4o-mini"),
            judge_api_key=judge_key or "",
            judge_base_url=os.getenv("LME_JUDGE_BASE_URL", "https://api.openai.com/v1"),
            judge_model=os.getenv("LME_JUDGE_MODEL", "gpt-4o"),
            retrieve_top_k=int(os.getenv("LME_RETRIEVE_TOP_K", "10")),
        )

    def env_status(self) -> dict[str, bool]:
        return {
            "METRONIX_MCP_API_KEY": bool(self.metronix_mcp_api_key),
            "LME_CHAT_API_KEY": bool(self.chat_api_key),
            "LME_JUDGE_API_KEY": bool(self.judge_api_key),
        }

    def apply_cli_overrides(
        self,
        *,
        chat_api_key: str | None = None,
        chat_base_url: str | None = None,
        chat_model: str | None = None,
        judge_api_key: str | None = None,
        judge_base_url: str | None = None,
        judge_model: str | None = None,
        workspace_id: str | None = None,
        retrieve_top_k: int | None = None,
    ) -> BenchConfig:
        return BenchConfig(
            metronix_mcp_api_key=self.metronix_mcp_api_key,
            metronix_mcp_url=self.metronix_mcp_url,
            metronix_api_url=self.metronix_api_url,
            workspace_id=workspace_id or self.workspace_id,
            chat_api_key=chat_api_key or self.chat_api_key,
            chat_base_url=chat_base_url or self.chat_base_url,
            chat_model=chat_model or self.chat_model,
            judge_api_key=judge_api_key or self.judge_api_key,
            judge_base_url=judge_base_url or self.judge_base_url,
            judge_model=judge_model or self.judge_model,
            retrieve_top_k=retrieve_top_k or self.retrieve_top_k,
            agent_id_prefix=self.agent_id_prefix,
        )
