"""Application settings loaded from environment variables.

Uses Pydantic BaseSettings for validation and .env file support.
Every setting has a sensible default for local development.
"""

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

    # --- Confluence ---
    confluence_url: str = Field("", alias="CONFLUENCE_URL")
    confluence_username: str = Field("", alias="CONFLUENCE_USERNAME")
    confluence_api_token: str = Field("", alias="CONFLUENCE_API_TOKEN")
    confluence_space_key: str = Field("", alias="CONFLUENCE_SPACE_KEY")

    # --- Jira ---
    jira_url: str = Field("", alias="JIRA_URL")
    jira_username: str = Field("", alias="JIRA_USERNAME")
    jira_api_token: str = Field("", alias="JIRA_API_TOKEN")
    jira_project_key: str = Field("", alias="JIRA_PROJECT_KEY")

    # --- Channels ---
    telegram_bot_token: str = Field("", alias="TELEGRAM_BOT_TOKEN")
    discord_bot_token: str = Field("", alias="DISCORD_BOT_TOKEN")
    slack_bot_token: str = Field("", alias="SLACK_BOT_TOKEN")
    slack_app_token: str = Field("", alias="SLACK_APP_TOKEN")
    slack_signing_secret: str = Field("", alias="SLACK_SIGNING_SECRET")

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
    sparse_weight: float = 0.20
    tag_weight: float = 0.20
    graph_weight: float = 0.15
    recency_weight: float = 0.10

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
        if host.startswith("http://") or host.startswith("https://"):
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
