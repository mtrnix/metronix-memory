"""Multi-provider LLM abstraction for Metatron.

Usage::

    from metatron.llm import chat_completion

    # Simple usage - uses configured provider
    result = chat_completion(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ]
    )
    print(result)  # "Hello! How can I help you today?"

    # With options
    result = chat_completion(
        messages=[...],
        temperature=0.1,
        max_tokens=500,
        json_mode=True,
    )

    # Direct provider access
    from metatron.llm import get_llm

    llm = get_llm()
    response = llm.chat_completion(messages=[...])
    print(response.content)
    print(response.model, response.provider)

Configuration via environment variables::

    LLM_PROVIDER=deepseek|openrouter|ollama|custom
    LLM_MODEL=model-name (optional, uses provider default)

    # Fallback (optional)
    LLM_FALLBACK_PROVIDER=ollama
    LLM_FALLBACK_MODEL=llama3

    # Provider-specific
    DEEPSEEK_API_KEY=sk-xxx
    OPENROUTER_API_KEY=sk-xxx
    OLLAMA_LLM_HOST=http://localhost:11434
    OLLAMA_LLM_MODEL=llama3
    CUSTOM_LLM_URL=http://server:8080/v1/chat/completions
"""

import time
from typing import Any, Dict, List, Optional, Union

import structlog

from metatron.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    LLMError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMAuthenticationError,
)
from metatron.llm.provider import (
    get_llm,
    create_provider,
    get_provider_class,
    get_fallback_provider,
    _get_cached_fallback,
    PROVIDERS,
)
from metatron.observability.metrics import timed

logger = structlog.get_logger()

__all__ = [
    # Public API
    "chat_completion",
    "chat_completion_with_retry",
    "get_llm",
    # Provider management
    "create_provider",
    "get_provider_class",
    "get_fallback_provider",
    "PROVIDERS",
    # Types and exceptions
    "LLMProvider",
    "LLMResponse",
    "Message",
    "LLMError",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
]


@timed("llm_completion")
def chat_completion(  # TODO: async migration
    messages: List[Union[Dict[str, str], Message]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
    timeout: int = 60,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    use_fallback: bool = True,
    **kwargs: Any,
) -> str:
    """Send a chat completion request to the configured LLM provider.

    This is the main entry point for LLM calls. It handles provider
    selection, fallback on failure, and returns just the response content.

    Args:
        messages: List of messages, either as dicts or Message objects.
        temperature: Sampling temperature (0-2, default 0.7).
        max_tokens: Maximum tokens in response (optional).
        json_mode: Request JSON output format (default False).
        timeout: Request timeout in seconds (default 60).
        provider: Provider name override (optional).
        model: Model name override (optional).
        use_fallback: Whether to try fallback provider on failure.
        **kwargs: Additional provider-specific parameters.

    Returns:
        Response content as string.

    Raises:
        LLMError: If all providers fail.
    """
    # Convert dicts to Message objects
    msg_objects: List[Message] = []
    for m in messages:
        if isinstance(m, Message):
            msg_objects.append(m)
        elif isinstance(m, dict):
            role = m.get("role")
            content = m.get("content")
            if not role or content is None:
                raise ValueError(
                    f"Invalid message format: missing 'role' or 'content' in {m}"
                )
            msg_objects.append(Message(role=role, content=content))
        else:
            raise ValueError(f"Invalid message type: {type(m)}")

    # Get primary provider
    llm = get_llm(provider_name=provider, model=model)

    try:
        response = llm.chat_completion(
            messages=msg_objects,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            timeout=timeout,
            **kwargs,
        )
        return response.content

    except (LLMConnectionError, LLMAuthenticationError, LLMRateLimitError) as e:
        logger.warning("primary_llm_failed", provider=llm.name, error=str(e))

        if not use_fallback:
            raise

        # Try fallback provider
        fallback = _get_cached_fallback()
        if fallback and fallback.is_available():
            logger.info("trying_fallback_provider", provider=fallback.name)
            try:
                response = fallback.chat_completion(
                    messages=msg_objects,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    timeout=timeout,
                    **kwargs,
                )
                return response.content
            except LLMError as fallback_error:
                logger.error(
                    "fallback_llm_failed",
                    provider=fallback.name,
                    error=str(fallback_error),
                )
                raise LLMError(
                    f"Primary ({llm.name}) and fallback ({fallback.name}) "
                    f"providers both failed. Primary error: {e}. "
                    f"Fallback error: {fallback_error}"
                ) from e

        # No fallback available
        raise


def chat_completion_with_retry(
    messages: List[Union[Dict[str, str], Message]],
    max_retries: int = 3,
    **kwargs: Any,
) -> str:
    """Chat completion with exponential backoff retry on connection errors.

    Retries only on LLMConnectionError (timeout, network). Auth and rate
    limit errors are raised immediately since retrying won't help.

    Args:
        messages: List of messages, either as dicts or Message objects.
        max_retries: Maximum number of attempts (default 3).
        **kwargs: Passed through to chat_completion().

    Returns:
        Response content as string.

    Raises:
        LLMConnectionError: If all retry attempts fail.
        LLMAuthenticationError: Immediately on auth failure.
        LLMRateLimitError: Immediately on rate limit.
        LLMError: On other non-retryable errors.
    """
    last_error: LLMConnectionError | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return chat_completion(messages=messages, **kwargs)
        except LLMConnectionError as e:
            last_error = e
            if attempt < max_retries:
                delay = 2 ** attempt  # 2s, 4s
                logger.warning(
                    "llm.retry",
                    attempt=attempt,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(e),
                )
                time.sleep(delay)
            # Auth/rate-limit errors bubble up from chat_completion
            # since they are NOT subclasses of LLMConnectionError
    raise last_error  # type: ignore[misc]
