# LLM

## Overview
L3 — LLM provider abstraction. Unified interface over Ollama (local), DeepSeek, OpenRouter,
and any OpenAI-compatible custom endpoint. Also handles embedding generation with TTL cache.
All providers are synchronous (TODO: async migration).

## Files

### `base.py`
`LLMProvider` — abstract base for all providers.

Abstract methods: `chat(messages, tools, temperature) -> LLMResponse`, `embed(texts) -> list[list[float]]`.

`LLMResponse` dataclass — `content: str`, `tool_calls: list[dict] | None`, `usage: dict`.
`Message` dataclass — `role: str`, `content: str`.

Exception hierarchy:
- `LLMError` — base
- `LLMConnectionError` — network failure
- `LLMRateLimitError` — 429, includes `retry_after`
- `LLMAuthenticationError` — 401/403

### `provider.py`
Factory + fallback logic.

`PROVIDERS = {"deepseek": DeepSeekProvider, "openrouter": OpenRouterProvider, "ollama": OllamaProvider, "custom": CustomProvider}`

`create_provider(provider_name, settings) -> LLMProvider`
— instantiates provider with settings-derived kwargs.

`get_llm(settings) -> LLMProvider`
— returns primary provider from `LLM_PROVIDER` setting. Module-level cached singleton.

`get_fallback_provider() -> LLMProvider | None`
— returns `LLM_FALLBACK_PROVIDER` provider (used when primary fails).

`_settings_for_provider(name, settings) -> dict`
— extracts per-provider kwargs: deepseek→`{api_key, model}`, ollama→`{model}`, custom→`{api_key, model, url}`.

### `embeddings.py`
Embedding generation with LRU cache.

`get_cached_embedding(text, model, ollama_host) -> list[float]`
— TTL cache (`EMBEDDING_CACHE_TTL=3600s`, `EMBEDDING_CACHE_MAXSIZE=2048`).
Calls Ollama embeddings API (`/api/embeddings`).

`get_embedding_cache_stats() -> dict` — hit/miss/size counts.
`clear_embedding_cache()` — invalidate all cached embeddings.

### `ollama.py`
`chat_completion(messages, workspace_id, settings) -> str`
— module-level convenience function used throughout retrieval and ingestion.
Calls `OllamaProvider.chat()` with retry.

`chat_completion_with_retry(messages, ..., max_retries=3) -> str`
— same with exponential backoff on `LLMConnectionError`.

### `openai_compat.py`
Shared helpers for OpenAI-compatible API calls (used by DeepSeek, OpenRouter, Custom).
`build_openai_payload(messages, tools, model, temperature) -> dict`
`parse_openai_response(response_json) -> LLMResponse`

### `providers/ollama.py`
`OllamaProvider` — calls `ollama_llm_url/api/chat` (POST).
Handles streaming and non-streaming responses.
Uses `core.http.get_http_session()` for connection reuse.

### `providers/deepseek.py`
`DeepSeekProvider` — calls `https://api.deepseek.com/chat/completions`.
Handles `RateLimitError` with `retry_after` from response headers.

### `providers/openrouter.py`
`OpenRouterProvider` — calls `https://openrouter.ai/api/v1/chat/completions`.
Sends `X-Title: {openrouter_app_name}` header. Supports multiple models via `OPENROUTER_MODEL`.

### `providers/custom.py`
`CustomProvider` — any OpenAI-compatible endpoint (`CUSTOM_LLM_URL`).
For vLLM, LocalAI, text-generation-webui, etc.

## Key Patterns
- **Module-level `get_llm()` singleton** — cached after first call; don't instantiate providers directly in business logic
- **Sync everywhere** — all providers use `requests` (not `httpx` or `aiohttp`); called via `asyncio.to_thread()` from async code
- **Fallback chain** — `LLM_FALLBACK_PROVIDER` for automatic failover; retrieval calls `chat_completion_with_retry()`
- **Embedding cache** — TTL+LRU prevents redundant embedding calls for repeated queries

## Dependencies
- **Depends on**: `core.config` (Settings), `core.http` (get_http_session)
- **Depended on by**: `retrieval.search` (chat_completion, chat_completion_with_retry), `ingestion.pipeline` (embed for chunked docs), `ingestion.processors.translation` (translate_to_english), `mcp.tools`
