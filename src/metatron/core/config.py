"""Application settings loaded from environment variables.

Uses Pydantic BaseSettings for validation and .env file support.
Every setting has a sensible default for local development.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — one instance injected everywhere via DI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    env: str = Field("development", alias="METATRON_ENV")
    host: str = Field("0.0.0.0", alias="METATRON_HOST")
    port: int = Field(8000, alias="METATRON_PORT")
    log_level: str = Field("INFO", alias="METATRON_LOG_LEVEL")
    secret_key: str = Field("change-me-in-production", alias="METATRON_SECRET_KEY")
    cors_origins: str = Field("*", alias="CORS_ORIGINS")

    # --- Auth ---
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    auth_password: str = Field(default="metatron", alias="AUTH_PASSWORD")

    # --- OpenAI-compatible API (for Open WebUI integration) ---
    openai_compat_enabled: bool = Field(True, alias="METATRON_OPENAI_COMPAT_ENABLED")
    openai_compat_key: str = Field("", alias="METATRON_OPENAI_COMPAT_KEY")

    # --- Open WebUI sync (bundled scenario) ---
    openwebui_url: str = Field("", alias="METATRON_OPENWEBUI_URL")
    openwebui_metatron_url: str = Field("", alias="METATRON_OPENWEBUI_METATRON_URL")

    # --- PostgreSQL ---
    postgres_host: str = Field("localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_db: str = Field("metatron", alias="POSTGRES_DB")
    postgres_user: str = Field("metatron", alias="POSTGRES_USER")
    postgres_password: str = Field("metatron_dev", alias="POSTGRES_PASSWORD")

    # --- Qdrant ---
    qdrant_host: str = Field("localhost", alias="QDRANT_HOST")
    qdrant_http_port: int = Field(6333, alias="QDRANT_HTTP_PORT")
    qdrant_grpc_port: int = Field(6334, alias="QDRANT_GRPC_PORT")

    # --- Memgraph ---
    memgraph_host: str = Field("localhost", alias="MEMGRAPH_HOST")
    memgraph_port: int = Field(7687, alias="MEMGRAPH_PORT")
    memgraph_user: str = Field("", alias="MEMGRAPH_USER")
    memgraph_password: str = Field("", alias="MEMGRAPH_PASSWORD")

    # --- Ollama (embeddings) ---
    ollama_host: str = Field("http://localhost:11434", alias="OLLAMA_HOST")
    ollama_chat_model: str = Field("llama3.1:8b", alias="OLLAMA_CHAT_MODEL")
    ollama_embed_model: str = Field("nomic-embed-text", alias="OLLAMA_EMBED_MODEL")

    # --- Ollama (LLM, separate from embeddings) ---
    ollama_llm_host: str = Field("", alias="OLLAMA_LLM_HOST")
    ollama_llm_port: int = Field(11434, alias="OLLAMA_LLM_PORT")
    ollama_llm_model: str = Field("llama3", alias="OLLAMA_LLM_MODEL")

    # --- LLM provider selection ---
    llm_provider: str = Field("ollama", alias="LLM_PROVIDER")
    llm_fallback_provider: str = Field("", alias="LLM_FALLBACK_PROVIDER")

    # --- DeepSeek ---
    deepseek_api_key: str = Field("", alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field("deepseek-chat", alias="DEEPSEEK_MODEL")

    # --- Benchmarker ---
    benchmarker_embedding_proxy_url: str = Field(
        "http://localhost:8001", alias="BENCHMARKER_EMBEDDING_PROXY_URL"
    )

    # --- OpenRouter ---
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        "meta-llama/llama-3.1-8b-instruct", alias="OPENROUTER_MODEL"
    )
    openrouter_app_name: str = Field("metatron", alias="OPENROUTER_APP_NAME")

    # --- Custom OpenAI-compatible LLM ---
    custom_llm_url: str = Field("", alias="CUSTOM_LLM_URL")
    custom_llm_api_key: str = Field("", alias="CUSTOM_LLM_API_KEY")
    custom_llm_model: str = Field("default", alias="CUSTOM_LLM_MODEL")

    # --- Encryption ---
    fernet_key: str = Field("", alias="FERNET_KEY")

    # --- File storage ---
    file_store_path: str = Field("./data/files", alias="FILE_STORE_PATH")

    # --- Workspace ---
    default_workspace_id: str = Field("MTRNIX", alias="DEFAULT_WORKSPACE_ID")
    default_workspace_name: str = Field("MTRNIX", alias="DEFAULT_WORKSPACE_NAME")
    workspace_persistence: str = Field("memgraph", alias="WORKSPACE_PERSISTENCE")

    # --- Search tuning ---
    search_max_total_chars: int = Field(40000, alias="SEARCH_MAX_TOTAL_CHARS")
    search_max_fragment_chars: int = Field(8000, alias="SEARCH_MAX_FRAGMENT_CHARS")
    search_pool_multiplier: int = Field(3, alias="SEARCH_POOL_MULTIPLIER")
    search_pool_min: int = Field(15, alias="SEARCH_POOL_MIN")
    bm25_vocab_size: int = Field(30000, alias="BM25_VOCAB_SIZE")
    query_expansion_enabled: bool = Field(True, alias="QUERY_EXPANSION_ENABLED")
    reranker_enabled: bool = Field(True, alias="RERANKER_ENABLED")
    query_classifier_enabled: bool = Field(True, alias="QUERY_CLASSIFIER_ENABLED")

    # Per-channel recall limits
    recall_top_n_dense: int = Field(30, alias="RECALL_TOP_N_DENSE")
    recall_top_n_exact: int = Field(10, alias="RECALL_TOP_N_EXACT")
    recall_top_n_metadata: int = Field(10, alias="RECALL_TOP_N_METADATA")
    recall_top_n_graph: int = Field(5, alias="RECALL_TOP_N_GRAPH")
    recall_graph_max_depth: int = Field(2, alias="RECALL_GRAPH_MAX_DEPTH")

    # --- LLM context budget ---
    llm_context_max_tokens: int = Field(10000, alias="LLM_CONTEXT_MAX_TOKENS")
    llm_answer_reserve_tokens: int = Field(1500, alias="LLM_ANSWER_RESERVE_TOKENS")

    # --- Graph extraction ---
    graph_extraction_enabled: bool = Field(True, alias="GRAPH_EXTRACTION_ENABLED")
    graph_extraction_workers: int = Field(4, alias="GRAPH_EXTRACTION_WORKERS")
    graph_extraction_min_chars: int = Field(100, alias="GRAPH_EXTRACTION_MIN_CHARS")

    # --- Embedding cache ---
    embedding_cache_ttl: int = Field(3600, alias="EMBEDDING_CACHE_TTL")
    embedding_cache_maxsize: int = Field(2048, alias="EMBEDDING_CACHE_MAXSIZE")

    # --- Retrieval tuning ---
    embedding_dim: int = 768
    rrf_k: int = 60
    dense_weight: float = 0.35
    sparse_weight: float = 0.0
    graph_weight: float = 0.15
    metadata_weight: float = 0.20
    recency_weight: float = 0.10
    balance_weight: float = 0.05
    blend_weight: float = 0.3
    rerank_pool_size: int = 35
    min_signal_score: float = 0.0  # 0.0 = disabled. Set > 0 to filter low-confidence results.

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS comma-separated string into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_sync_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def memgraph_uri(self) -> str:
        return f"bolt://{self.memgraph_host}:{self.memgraph_port}"

    @property
    def ollama_llm_url(self) -> str:
        host = self.ollama_llm_host or self.ollama_host
        if host.startswith(("http://", "https://")):
            # Already a full URL — check if port is included
            from urllib.parse import urlparse
            parsed = urlparse(host)
            if parsed.port:
                return host
            return f"{host}:{self.ollama_llm_port}"
        return f"http://{host}:{self.ollama_llm_port}"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            msg = f"log_level must be one of {allowed}, got '{v}'"
            raise ValueError(msg)
        return upper

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            msg = f"env must be one of {allowed}, got '{v}'"
            raise ValueError(msg)
        return v


# --- Cached singleton ---------------------------------------------------

_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance (created once from env)."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings
