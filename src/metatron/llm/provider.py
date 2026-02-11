"""LLM provider factory with fallback support."""

import os
from typing import Dict, Optional, Type

import structlog

from metatron.llm.base import LLMProvider, LLMError, LLMConnectionError, LLMAuthenticationError
from metatron.llm.providers import (
    DeepSeekProvider,
    OpenRouterProvider,
    OllamaProvider,
    CustomProvider,
)

logger = structlog.get_logger()

# Registry of available providers
PROVIDERS: Dict[str, Type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "custom": CustomProvider,
}


def get_provider_class(name: str) -> Type[LLMProvider]:
    """Get provider class by name."""
    provider_class = PROVIDERS.get(name.lower())
    if not provider_class:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown LLM provider: {name}. Available: {available}")
    return provider_class


def create_provider(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider_name: Provider name (deepseek, openrouter, ollama, custom).
                      Falls back to LLM_PROVIDER env var, then "deepseek".
        model: Model name override (provider-specific).
               Falls back to LLM_MODEL env var, then provider default.
        **kwargs: Additional provider-specific configuration.

    Returns:
        Configured LLMProvider instance.
    """
    provider_name = provider_name or os.getenv("LLM_PROVIDER", "deepseek")
    model = model or os.getenv("LLM_MODEL")

    provider_class = get_provider_class(provider_name)
    return provider_class(model=model, **kwargs)


def get_fallback_provider() -> Optional[LLMProvider]:
    """Get fallback provider if configured.

    Returns:
        LLMProvider instance or None if not configured.
    """
    fallback_name = os.getenv("LLM_FALLBACK_PROVIDER")
    if not fallback_name:
        return None

    fallback_model = os.getenv("LLM_FALLBACK_MODEL")

    try:
        provider = create_provider(fallback_name, fallback_model)
        if provider.is_available():
            return provider
        logger.warning(
            "fallback_provider_not_available",
            provider=fallback_name,
        )
    except Exception as e:
        logger.warning(
            "fallback_provider_creation_failed",
            provider=fallback_name,
            error=str(e),
        )

    return None


# Cached primary and fallback providers
_primary_provider: Optional[LLMProvider] = None
_fallback_provider: Optional[LLMProvider] = None


def get_llm(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    use_cache: bool = True,
    **kwargs,
) -> LLMProvider:
    """Get an LLM provider instance.

    Uses cached instance by default for efficiency.

    Args:
        provider_name: Provider name override.
        model: Model name override.
        use_cache: Whether to use cached provider instance.
        **kwargs: Additional provider-specific configuration.

    Returns:
        Configured LLMProvider instance.
    """
    global _primary_provider

    # Return cached provider if available and no overrides
    if (
        use_cache
        and _primary_provider
        and not provider_name
        and not model
        and not kwargs
    ):
        return _primary_provider

    provider = create_provider(provider_name, model, **kwargs)

    # Cache if no overrides
    if use_cache and not provider_name and not model and not kwargs:
        _primary_provider = provider

    return provider


def _get_cached_fallback() -> Optional[LLMProvider]:
    """Get cached fallback provider."""
    global _fallback_provider

    if _fallback_provider is None:
        _fallback_provider = get_fallback_provider()

    return _fallback_provider
