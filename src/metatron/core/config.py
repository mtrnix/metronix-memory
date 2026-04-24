"""Application settings loaded from environment variables.

Uses Pydantic BaseSettings for validation and .env file support.
Every setting has a sensible default for local development.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
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
    qdrant_api_key: str = Field("", alias="QDRANT_API_KEY")
    qdrant_https: bool = Field(False, alias="QDRANT_HTTPS")

    # --- Neo4j (graph database) ---
    neo4j_host: str = Field(
        "localhost",
        validation_alias=AliasChoices("NEO4J_HOST", "MEMGRAPH_HOST"),
    )
    neo4j_port: int = Field(
        7687,
        validation_alias=AliasChoices("NEO4J_PORT", "MEMGRAPH_PORT"),
    )
    neo4j_user: str = Field(
        "",
        validation_alias=AliasChoices("NEO4J_USER", "MEMGRAPH_USER"),
    )
    neo4j_password: str = Field(
        "",
        validation_alias=AliasChoices("NEO4J_PASSWORD", "MEMGRAPH_PASSWORD"),
    )

    # --- Redis ---
    redis_host: str = Field("localhost", alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")
    redis_db: int = Field(0, alias="REDIS_DB")
    redis_password: str = Field("", alias="REDIS_PASSWORD")
    memory_session_ttl: int = Field(14400, alias="METATRON_MEMORY_SESSION_TTL")  # 4 hours
    memory_search_dense_weight: float = Field(0.6, alias="METATRON_MEMORY_SEARCH_DENSE_WEIGHT")
    memory_search_graph_weight: float = Field(0.3, alias="METATRON_MEMORY_SEARCH_GRAPH_WEIGHT")
    memory_search_session_weight: float = Field(0.1, alias="METATRON_MEMORY_SEARCH_SESSION_WEIGHT")
    memory_search_top_k_multiplier: int = Field(3, alias="METATRON_MEMORY_SEARCH_TOP_K_MULTIPLIER")

    # --- Fast search profile (metatron_search_fast MCP tool) ---
    search_fast_top_k: int = Field(10, alias="METATRON_SEARCH_FAST_TOP_K")
    search_fast_include_metadata: bool = Field(
        True,
        alias="METATRON_SEARCH_FAST_INCLUDE_METADATA",
    )

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
    openrouter_model: str = Field("meta-llama/llama-3.1-8b-instruct", alias="OPENROUTER_MODEL")
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
    workspace_persistence: str = Field("neo4j", alias="WORKSPACE_PERSISTENCE")

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

    # --- Hierarchical chunking ---
    hierarchical_chunking_enabled: bool = Field(
        True, alias="METATRON_HIERARCHICAL_CHUNKING_ENABLED"
    )

    # --- Graph extraction ---
    graph_extraction_enabled: bool = Field(True, alias="GRAPH_EXTRACTION_ENABLED")
    graph_extraction_workers: int = Field(1, alias="GRAPH_EXTRACTION_WORKERS")
    graph_extraction_min_chars: int = Field(100, alias="GRAPH_EXTRACTION_MIN_CHARS")

    # --- Embedding cache ---
    embedding_cache_ttl: int = Field(3600, alias="EMBEDDING_CACHE_TTL")
    embedding_cache_maxsize: int = Field(2048, alias="EMBEDDING_CACHE_MAXSIZE")
    # Caps concurrent ingest-path Ollama embedding calls so mass document
    # ingestion does not starve concurrent query embeddings. Query path
    # (``get_cached_embedding``) is deliberately NOT throttled — searches
    # always get priority at the Ollama instance.
    ingest_embed_concurrency: int = Field(2, alias="INGEST_EMBED_CONCURRENCY")

    # --- Retrieval tuning ---
    embedding_dim: int = 768
    rrf_k: int = 60
    adaptive_rrf_enabled: bool = Field(False, alias="ADAPTIVE_RRF_ENABLED")
    rrf_k_low: int = Field(20, alias="RRF_K_LOW")
    rrf_k_high: int = Field(80, alias="RRF_K_HIGH")
    rrf_overlap_threshold_low: float = Field(0.2, alias="RRF_OVERLAP_THRESHOLD_LOW")
    rrf_overlap_threshold_high: float = Field(0.7, alias="RRF_OVERLAP_THRESHOLD_HIGH")
    dense_weight: float = 0.35
    sparse_weight: float = 0.0
    graph_weight: float = 0.15
    metadata_weight: float = 0.20
    recency_weight: float = 0.10
    balance_weight: float = 0.05
    blend_weight: float = 0.3
    rerank_pool_size: int = 35
    min_signal_score: float = 0.0  # 0.0 = disabled. Set > 0 to filter low-confidence results.

    # --- HyDE (Hypothetical Document Embedding) ---
    hyde_enabled: bool = Field(False, alias="HYDE_ENABLED")
    hyde_max_words: int = Field(4, alias="HYDE_MAX_WORDS")
    hyde_timeout: int = Field(8, alias="HYDE_TIMEOUT")

    # --- SPLADE sparse representations ---
    splade_enabled: bool = Field(True, alias="SPLADE_ENABLED")
    splade_model: str = Field("naver/splade-cocondenser-ensembledistil", alias="SPLADE_MODEL")
    splade_max_length: int = Field(256, alias="SPLADE_MAX_LENGTH")
    splade_service_url: str = Field("", alias="SPLADE_SERVICE_URL")

    # --- Freshness pipeline (MTRNIX-304) ---
    # Master flag. When False: producer is a no-op and `python -m metatron.memory.freshness`
    # exits immediately. All existing memory flows must behave identically.
    freshness_enabled: bool = Field(default=False, alias="METATRON_FRESHNESS_ENABLED")
    freshness_poll_seconds: float = Field(default=2.0, alias="METATRON_FRESHNESS_POLL_SECONDS")
    freshness_max_jobs_per_iteration: int = Field(
        default=20, alias="METATRON_FRESHNESS_MAX_JOBS_PER_ITERATION"
    )
    freshness_lock_ttl_seconds: int = Field(
        default=30, alias="METATRON_FRESHNESS_LOCK_TTL_SECONDS"
    )
    freshness_stale_after_days: int = Field(
        default=30, alias="METATRON_FRESHNESS_STALE_AFTER_DAYS"
    )
    freshness_decision_confidence_threshold: float = Field(
        default=0.7, alias="METATRON_FRESHNESS_DECISION_CONFIDENCE_THRESHOLD"
    )
    freshness_llm_model: str = Field(
        default="qwen2.5-4b-instruct-q4", alias="METATRON_FRESHNESS_LLM_MODEL"
    )
    freshness_llm_provider: str = Field(default="", alias="METATRON_FRESHNESS_LLM_PROVIDER")
    freshness_llm_api_base_url: str = Field(
        default="", alias="METATRON_FRESHNESS_LLM_API_BASE_URL"
    )
    freshness_llm_api_key: str = Field(default="", alias="METATRON_FRESHNESS_LLM_API_KEY")
    freshness_linker_threshold: float = Field(
        default=0.6, alias="METATRON_FRESHNESS_LINKER_THRESHOLD"
    )
    freshness_reconciler_threshold: float = Field(
        default=0.85, alias="METATRON_FRESHNESS_RECONCILER_THRESHOLD"
    )
    freshness_backoff_base_seconds: float = Field(
        default=2.0, alias="METATRON_FRESHNESS_BACKOFF_BASE_SECONDS"
    )
    freshness_backoff_max_seconds: float = Field(
        default=60.0, alias="METATRON_FRESHNESS_BACKOFF_MAX_SECONDS"
    )
    freshness_max_consecutive_errors: int = Field(
        default=10, alias="METATRON_FRESHNESS_MAX_CONSECUTIVE_ERRORS"
    )
    # --- Freshness queue reliability (MTRNIX-316) ---
    freshness_heartbeat_ttl_seconds: int = Field(
        default=20,
        alias="METATRON_FRESHNESS_HEARTBEAT_TTL_SECONDS",
        description="Worker heartbeat key TTL. Reclaim considers a worker dead when missing.",
    )
    freshness_reclaim_interval_iterations: int = Field(
        default=30,
        alias="METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS",
        description="Reclaim pass cadence inside the worker loop (iterations).",
    )
    freshness_scheduled_scan_enabled: bool = Field(
        default=True,
        alias="METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED",
        description="Master flag for the safety-net scheduled scan.",
    )
    freshness_scheduled_scan_interval_seconds: int = Field(
        default=3600,
        alias="METATRON_FRESHNESS_SCHEDULED_SCAN_INTERVAL_SECONDS",
        description="Scheduled-scan cadence (seconds).",
    )
    freshness_scan_batch_limit: int = Field(
        default=500,
        alias="METATRON_FRESHNESS_SCAN_BATCH_LIMIT",
        description="Cap per-workspace stale candidates enqueued per scan.",
    )
    freshness_drain_legacy_at_startup: bool = Field(
        default=False,
        alias="METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP",
        description="One-time flag for env-prefix rollout (legacy unprefixed → prefixed drain).",
    )
    # --- KB-freshness (Phase B, MTRNIX-313) ---
    freshness_kb_enabled: bool = Field(
        default=False,
        alias="METATRON_FRESHNESS_KB_ENABLED",
        description="KB-side freshness producer flag. Requires freshness_enabled=True.",
    )
    freshness_kb_search_filter_enabled: bool = Field(
        default=False,
        alias="METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED",
        description="Retrieval-side ARCHIVED/SUPERSEDED filter flag.",
    )
    freshness_weight: float = Field(
        default=0.0,
        alias="METATRON_FRESHNESS_WEIGHT",
        description="Scoring weight for the freshness signal. 0.0 = off.",
    )
    freshness_kb_stale_after_days: int = Field(
        default=90,
        alias="METATRON_FRESHNESS_KB_STALE_AFTER_DAYS",
        description="KB stale threshold in days (default 90 vs. memory's 30).",
    )

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
    def neo4j_uri(self) -> str:
        return f"bolt://{self.neo4j_host}:{self.neo4j_port}"

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

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
