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
    env: str = Field("development", alias="METRONIX_ENV")
    host: str = Field("0.0.0.0", alias="METRONIX_HOST")
    port: int = Field(8000, alias="METRONIX_PORT")
    log_level: str = Field("INFO", alias="METRONIX_LOG_LEVEL")
    secret_key: str = Field("change-me-in-production", alias="METRONIX_SECRET_KEY")
    cors_origins: str = Field("*", alias="CORS_ORIGINS")

    # --- Auth ---
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    auth_password: str = Field(default="metronix", alias="AUTH_PASSWORD")

    # --- OpenAI-compatible API (for Open WebUI integration) ---
    openai_compat_enabled: bool = Field(True, alias="METRONIX_OPENAI_COMPAT_ENABLED")
    openai_compat_key: str = Field("", alias="METRONIX_OPENAI_COMPAT_KEY")

    # --- Open WebUI sync (bundled scenario) ---
    openwebui_url: str = Field("", alias="METRONIX_OPENWEBUI_URL")
    openwebui_metronix_url: str = Field("", alias="METRONIX_OPENWEBUI_METRONIX_URL")

    # --- PostgreSQL ---
    postgres_host: str = Field("localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_db: str = Field("metronix", alias="POSTGRES_DB")
    postgres_user: str = Field("metronix", alias="POSTGRES_USER")
    postgres_password: str = Field("metronix_dev", alias="POSTGRES_PASSWORD")

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
    memory_session_ttl: int = Field(14400, alias="METRONIX_MEMORY_SESSION_TTL")  # 4 hours
    memory_session_gc_grace_hours: int = Field(
        24,
        alias="METRONIX_MEMORY_SESSION_GC_GRACE_HOURS",
        ge=0,
        description=(
            "Hours past ttl_expires_at before the scheduled-scan GC pass deletes the PG copy "
            "of a session record. 0 = delete immediately on expiry."
        ),
    )
    memory_search_dense_weight: float = Field(0.6, alias="METRONIX_MEMORY_SEARCH_DENSE_WEIGHT")
    memory_search_graph_weight: float = Field(0.3, alias="METRONIX_MEMORY_SEARCH_GRAPH_WEIGHT")
    memory_search_session_weight: float = Field(0.1, alias="METRONIX_MEMORY_SEARCH_SESSION_WEIGHT")
    memory_search_top_k_multiplier: int = Field(3, alias="METRONIX_MEMORY_SEARCH_TOP_K_MULTIPLIER")
    # --- Memory health (MTRNIX-277) ---
    memory_stale_after_days: int = Field(30, alias="METRONIX_MEMORY_STALE_AFTER_DAYS")
    memory_duplicate_hamming_threshold: int = Field(
        3, alias="METRONIX_MEMORY_DUPLICATE_HAMMING_THRESHOLD"
    )

    # --- Memory snapshots (WS1 stages 4-5, MTRNIX-272) ---
    snapshot_dir: str = Field("./data/snapshots", alias="METRONIX_SNAPSHOT_DIR")
    snapshot_max_file_bytes: int = Field(
        256 * 1024 * 1024,
        alias="METRONIX_SNAPSHOT_MAX_FILE_BYTES",
    )

    # --- Fast search profile (metronix_search_fast MCP tool) ---
    search_fast_top_k: int = Field(10, alias="METRONIX_SEARCH_FAST_TOP_K")
    search_fast_include_metadata: bool = Field(
        True,
        alias="METRONIX_SEARCH_FAST_INCLUDE_METADATA",
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
    # MTRNIX-397 (A): FAST tier for service LLM calls (resolve/expand/classify/NER/slots).
    # Empty string => inherit the heavy `deepseek_model` at runtime, so an unset FAST var is
    # byte-identical to today even with a custom DEEPSEEK_MODEL. Only used by the deepseek
    # provider; tiering is a no-op for other providers (see metronix.llm.tiers).
    deepseek_model_fast: str = Field("", alias="DEEPSEEK_MODEL_FAST")

    # --- Benchmarker ---
    benchmarker_embedding_proxy_url: str = Field(
        "http://localhost:8001", alias="BENCHMARKER_EMBEDDING_PROXY_URL"
    )

    # --- OpenRouter ---
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field("meta-llama/llama-3.1-8b-instruct", alias="OPENROUTER_MODEL")
    openrouter_app_name: str = Field("metronix", alias="OPENROUTER_APP_NAME")

    # --- Custom OpenAI-compatible LLM ---
    custom_llm_url: str = Field("", alias="CUSTOM_LLM_URL")
    custom_llm_api_key: str = Field("", alias="CUSTOM_LLM_API_KEY")
    custom_llm_model: str = Field("default", alias="CUSTOM_LLM_MODEL")

    # --- Generic OpenAI-compatible provider (preferred) ---
    # Single endpoint + key used by the ``custom`` provider. Takes precedence over
    # the legacy CUSTOM_LLM_* vars, which remain as a fallback for older .env files.
    llm_provider_url: str = Field("", alias="LLM_PROVIDER_URL")
    llm_provider_api_key: str = Field("", alias="LLM_PROVIDER_API_KEY")

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
        True, alias="METRONIX_HIERARCHICAL_CHUNKING_ENABLED"
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
    # MTRNIX-397 (S1): normalize the signal score by the weights of channels that actually
    # returned results for the query (query-level), instead of by the sum of ALL weights.
    # Prevents the score collapsing to source-balance noise when metadata/graph channels are
    # empty. Mathematically inert when every weighted channel returns >=1 result.
    retrieval_scoring_normalize_active_only: bool = Field(
        True, alias="METRONIX_RETRIEVAL_SCORING_NORMALIZE_ACTIVE_ONLY"
    )
    # MTRNIX-397 (B0): FAST-LLM slot extraction feeds channel triggers (dates/people/jira
    # keys/entities/activity) on top of regex. Default off — when off the regex path is used
    # unchanged. Hardened: timeout + strict JSON parse + fallback to regex on any failure.
    retrieval_slot_extraction_enabled: bool = Field(
        False, alias="METRONIX_RETRIEVAL_SLOT_EXTRACTION_ENABLED"
    )
    retrieval_slot_extraction_timeout: int = Field(
        6, alias="METRONIX_RETRIEVAL_SLOT_EXTRACTION_TIMEOUT"
    )
    # MTRNIX-397 (G1): seed the graph recall channel from extracted entities instead of the
    # broken get_graph_entities(query) exact-text-match NER path. Default off.
    retrieval_graph_ner_enabled: bool = Field(
        False, alias="METRONIX_RETRIEVAL_GRAPH_NER_ENABLED"
    )
    # MTRNIX-397 (M6): when a resolved date is beyond the corpus, fall back to recent
    # in-progress items instead of returning nothing. Default off.
    retrieval_future_date_fallback_enabled: bool = Field(
        False, alias="METRONIX_RETRIEVAL_FUTURE_DATE_FALLBACK_ENABLED"
    )

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
    # Master flag. When False: producer is a no-op and `python -m metronix.memory.freshness`
    # exits immediately. All existing memory flows must behave identically.
    freshness_enabled: bool = Field(default=False, alias="METRONIX_FRESHNESS_ENABLED")
    freshness_poll_seconds: float = Field(default=2.0, alias="METRONIX_FRESHNESS_POLL_SECONDS")
    freshness_max_jobs_per_iteration: int = Field(
        default=20, alias="METRONIX_FRESHNESS_MAX_JOBS_PER_ITERATION"
    )
    freshness_lock_ttl_seconds: int = Field(
        default=30, alias="METRONIX_FRESHNESS_LOCK_TTL_SECONDS"
    )
    freshness_stale_after_days: int = Field(
        default=30, alias="METRONIX_FRESHNESS_STALE_AFTER_DAYS"
    )
    freshness_decision_confidence_threshold: float = Field(
        default=0.7, alias="METRONIX_FRESHNESS_DECISION_CONFIDENCE_THRESHOLD"
    )
    freshness_llm_model: str = Field(
        default="qwen2.5-4b-instruct-q4", alias="METRONIX_FRESHNESS_LLM_MODEL"
    )
    freshness_llm_provider: str = Field(default="", alias="METRONIX_FRESHNESS_LLM_PROVIDER")
    freshness_llm_api_base_url: str = Field(
        default="", alias="METRONIX_FRESHNESS_LLM_API_BASE_URL"
    )
    freshness_llm_api_key: str = Field(default="", alias="METRONIX_FRESHNESS_LLM_API_KEY")

    # --- Data export (one-time-token ZIP export) ---
    public_base_url: str = Field(default="", alias="METRONIX_PUBLIC_BASE_URL")
    # Default lives under /app/data, which docker-compose mounts as a persistent
    # named volume (full_file_data:/app/data); /data alone is ephemeral container
    # storage and would lose archives on restart and across workers.
    export_dir: str = Field(default="/app/data/exports", alias="METRONIX_EXPORT_DIR")
    export_token_ttl_seconds: int = Field(
        default=3600, alias="METRONIX_EXPORT_TOKEN_TTL_SECONDS", ge=60
    )
    export_disk_cap_bytes: int = Field(
        default=5_000_000_000, alias="METRONIX_EXPORT_DISK_CAP_BYTES", ge=0
    )
    export_job_watchdog_seconds: int = Field(
        default=3600, alias="METRONIX_EXPORT_JOB_WATCHDOG_SECONDS", ge=60
    )
    freshness_linker_threshold: float = Field(
        default=0.6, alias="METRONIX_FRESHNESS_LINKER_THRESHOLD"
    )
    freshness_reconciler_threshold: float = Field(
        default=0.85, alias="METRONIX_FRESHNESS_RECONCILER_THRESHOLD"
    )
    freshness_backoff_base_seconds: float = Field(
        default=2.0, alias="METRONIX_FRESHNESS_BACKOFF_BASE_SECONDS"
    )
    freshness_backoff_max_seconds: float = Field(
        default=60.0, alias="METRONIX_FRESHNESS_BACKOFF_MAX_SECONDS"
    )
    freshness_max_consecutive_errors: int = Field(
        default=10, alias="METRONIX_FRESHNESS_MAX_CONSECUTIVE_ERRORS"
    )
    # --- Freshness queue reliability (MTRNIX-316) ---
    freshness_heartbeat_ttl_seconds: int = Field(
        default=20,
        alias="METRONIX_FRESHNESS_HEARTBEAT_TTL_SECONDS",
        description="Worker heartbeat key TTL. Reclaim considers a worker dead when missing.",
    )
    freshness_reclaim_interval_iterations: int = Field(
        default=30,
        alias="METRONIX_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS",
        description="Reclaim pass cadence inside the worker loop (iterations).",
    )
    freshness_scheduled_scan_enabled: bool = Field(
        default=True,
        alias="METRONIX_FRESHNESS_SCHEDULED_SCAN_ENABLED",
        description="Master flag for the safety-net scheduled scan.",
    )
    freshness_scheduled_scan_interval_seconds: int = Field(
        default=3600,
        alias="METRONIX_FRESHNESS_SCHEDULED_SCAN_INTERVAL_SECONDS",
        description="Scheduled-scan cadence (seconds).",
    )
    freshness_scan_batch_limit: int = Field(
        default=500,
        alias="METRONIX_FRESHNESS_SCAN_BATCH_LIMIT",
        description="Cap per-workspace stale candidates enqueued per scan.",
    )
    freshness_drain_legacy_at_startup: bool = Field(
        default=False,
        alias="METRONIX_FRESHNESS_DRAIN_LEGACY_AT_STARTUP",
        description="One-time flag for env-prefix rollout (legacy unprefixed → prefixed drain).",
    )
    # --- KB-freshness (Phase B, MTRNIX-313) ---
    freshness_kb_enabled: bool = Field(
        default=False,
        alias="METRONIX_FRESHNESS_KB_ENABLED",
        description="KB-side freshness producer flag. Requires freshness_enabled=True.",
    )
    freshness_kb_search_filter_enabled: bool = Field(
        default=False,
        alias="METRONIX_FRESHNESS_KB_SEARCH_FILTER_ENABLED",
        description="Retrieval-side ARCHIVED/SUPERSEDED filter flag.",
    )
    freshness_weight: float = Field(
        default=0.0,
        alias="METRONIX_FRESHNESS_WEIGHT",
        description="Scoring weight for the freshness signal. 0.0 = off.",
    )
    freshness_kb_stale_after_days: int = Field(
        default=90,
        alias="METRONIX_FRESHNESS_KB_STALE_AFTER_DAYS",
        description="KB stale threshold in days (default 90 vs. memory's 30).",
    )

    # --- Memory Context Assembler (MTRNIX-275) ---
    memory_injection_enabled: bool = Field(
        default=False,
        alias="METRONIX_MEMORY_INJECTION_ENABLED",
        description="Master flag for memory context injection. When off, assembler returns "
        "empty context and MCP tool returns empty system_prompt.",
    )
    memory_injection_facts_top_k: int = Field(
        default=10,
        alias="METRONIX_MEMORY_INJECTION_FACTS_TOP_K",
        description="Number of fact-type memories to retrieve per assembly call.",
    )
    memory_injection_preferences_budget_tokens: int = Field(
        default=2000,
        alias="METRONIX_MEMORY_INJECTION_PREFERENCES_BUDGET_TOKENS",
        description="Soft token budget for <preferences> section. Warning-only (DD-5).",
    )
    memory_injection_facts_budget_tokens: int = Field(
        default=3000,
        alias="METRONIX_MEMORY_INJECTION_FACTS_BUDGET_TOKENS",
        description="Soft token budget for <relevant_memories> section. Warning-only (DD-5).",
    )

    # --- Agent activity logging (WS4 Stage 6) ---
    activity_log_enabled: bool = Field(
        default=True,
        alias="METRONIX_ACTIVITY_LOG_ENABLED",
    )

    # --- LLM generation telemetry (MTRNIX-336) ---
    llm_telemetry_enabled: bool = Field(
        default=True,
        alias="METRONIX_LLM_TELEMETRY_ENABLED",
        description="Master kill-switch. false → all telemetry is a no-op.",
    )
    llm_telemetry_retention_days: int = Field(
        default=0,
        alias="METRONIX_LLM_TELEMETRY_RETENTION_DAYS",
        description="Placeholder. 0 = infinite. No cleanup worker in this ticket.",
    )
    llm_telemetry_opt_out_cache_ttl_seconds: int = Field(
        default=60,
        alias="METRONIX_LLM_TELEMETRY_OPT_OUT_CACHE_TTL_SECONDS",
        description="TTL for workspace opt-out flag cache.",
    )

    # --- Proxy LLM (MTRNIX-372) ---
    # Default OFF until the integration gate (golden SSE + proxy e2e) passes on a
    # deployment — keeps legacy /v1/chat/completions on its inline path so the
    # A-full rag delegation cannot silently change behaviour (review W3).
    proxy_enabled: bool = Field(default=False, alias="METRONIX_PROXY_ENABLED")
    proxy_query_rewrite_enabled: bool = Field(
        default=False, alias="METRONIX_PROXY_QUERY_REWRITE_ENABLED"
    )
    proxy_tool_result_enrichment: bool = Field(
        default=True, alias="METRONIX_PROXY_TOOL_RESULT_ENRICHMENT"
    )
    proxy_query_rewrite_timeout_ms: int = Field(
        default=400, alias="METRONIX_PROXY_QUERY_REWRITE_TIMEOUT_MS"
    )
    proxy_memory_search_timeout_ms: int = Field(
        default=800, alias="METRONIX_PROXY_MEMORY_SEARCH_TIMEOUT_MS"
    )
    proxy_knowledge_search_timeout_ms: int = Field(
        default=800, alias="METRONIX_PROXY_KNOWLEDGE_SEARCH_TIMEOUT_MS"
    )
    proxy_tool_result_enrichment_timeout_ms: int = Field(
        default=500, alias="METRONIX_PROXY_TOOL_RESULT_ENRICHMENT_TIMEOUT_MS"
    )
    proxy_upstream_timeout_ms: int = Field(
        default=120000, alias="METRONIX_PROXY_UPSTREAM_TIMEOUT_MS"
    )
    proxy_knowledge_top_k: int = Field(default=5, alias="METRONIX_PROXY_KNOWLEDGE_TOP_K")
    proxy_entity_trie_ttl_seconds: int = Field(
        default=600, alias="METRONIX_PROXY_ENTITY_TRIE_TTL_SECONDS"
    )
    proxy_entity_trie_max_entities_per_ws: int = Field(
        default=50000, alias="METRONIX_PROXY_ENTITY_TRIE_MAX_ENTITIES_PER_WS"
    )
    proxy_default_upstream_key: str = Field(
        default="", alias="METRONIX_PROXY_DEFAULT_UPSTREAM_KEY"
    )

    # --- Autosync scheduler (MTRNIX-396) ---
    autosync_enabled: bool = Field(
        default=True,
        alias="METRONIX_AUTOSYNC_ENABLED",
        description="Master flag for the in-process autosync scheduler. "
        "When false the scheduler loop is not started.",
    )
    autosync_timezone: str = Field(
        default="UTC",
        alias="METRONIX_AUTOSYNC_TIMEZONE",
        description="IANA timezone used to interpret cron expressions (e.g. 'Europe/Amsterdam').",
    )
    autosync_poll_seconds: float = Field(
        default=60.0,
        alias="METRONIX_AUTOSYNC_POLL_SECONDS",
        description="Scheduler tick interval in seconds.",
    )
    autosync_max_concurrent: int = Field(
        default=2,
        alias="METRONIX_AUTOSYNC_MAX_CONCURRENT",
        description="Maximum number of autosync tasks that may run concurrently per API process.",
    )

    # --- RAG debug trace (full pipeline trace for answer debugging) ---
    rag_trace_enabled: bool = Field(
        default=True,
        alias="METRONIX_RAG_TRACE_ENABLED",
        description="Master flag for RAG debug-trace capture (collect phases + persist row). "
        "Does NOT gate the read endpoints.",
    )
    rag_trace_footer_enabled: bool = Field(
        default=True,
        alias="METRONIX_RAG_TRACE_FOOTER_ENABLED",
        description="Append the '— trace: <id>' footer to the user-visible answer. "
        "Independent of capture so the tail can be hidden while still tracing.",
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
