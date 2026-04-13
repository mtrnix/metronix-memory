"""LLM provider factory with fallback support."""

import structlog

from metatron.core.config import Settings
from metatron.llm.base import LLMProvider
from metatron.llm.providers import (
    CustomProvider,
    DeepSeekProvider,
    OllamaProvider,
    OpenRouterProvider,
)

logger = structlog.get_logger()

# Registry of available providers
PROVIDERS: dict[str, type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "custom": CustomProvider,
}


def _settings_for_provider(name: str, settings: Settings) -> dict:
    """Extract provider-specific kwargs from Settings."""
    if name == "deepseek":
        return {"api_key": settings.deepseek_api_key, "model": settings.deepseek_model}
    if name == "openrouter":
        return {"api_key": settings.openrouter_api_key, "model": settings.openrouter_model}
    if name == "ollama":
        return {"model": settings.ollama_llm_model}
    if name == "custom":
        return {
            "api_key": settings.custom_llm_api_key,
            "model": settings.custom_llm_model,
            "api_url": settings.custom_llm_url,
        }
    return {}


def get_provider_class(name: str) -> type[LLMProvider]:
    """Get provider class by name."""
    provider_class = PROVIDERS.get(name.lower())
    if not provider_class:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown LLM provider: {name}. Available: {available}")
    return provider_class


def create_provider(
    provider_name: str | None = None,
    model: str | None = None,
    **kwargs,
) -> LLMProvider:
    """Create an LLM provider instance from Settings."""
    settings = Settings()
    provider_name = provider_name or settings.llm_provider
    provider_class = get_provider_class(provider_name)

    # Merge settings defaults with explicit overrides
    defaults = _settings_for_provider(provider_name, settings)
    if model:
        defaults["model"] = model
    defaults.update(kwargs)

    return provider_class(**defaults)


def get_fallback_provider() -> LLMProvider | None:
    """Get fallback provider if configured."""
    settings = Settings()
    fallback_name = settings.llm_fallback_provider
    if not fallback_name:
        return None

    try:
        provider = create_provider(fallback_name)
        if provider.is_available():
            return provider
        logger.warning("fallback_provider_not_available", provider=fallback_name)
    except Exception as e:
        logger.warning("fallback_provider_creation_failed", provider=fallback_name, error=str(e))
    return None


# Cached primary and fallback providers
_primary_provider: LLMProvider | None = None
_fallback_provider: LLMProvider | None = None


def get_llm(
    provider_name: str | None = None,
    model: str | None = None,
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
    if use_cache and _primary_provider and not provider_name and not model and not kwargs:
        return _primary_provider

    provider = create_provider(provider_name, model, **kwargs)

    # Cache if no overrides
    if use_cache and not provider_name and not model and not kwargs:
        _primary_provider = provider

    return provider


def _get_cached_fallback() -> LLMProvider | None:
    """Get cached fallback provider."""
    global _fallback_provider

    if _fallback_provider is None:
        _fallback_provider = get_fallback_provider()

    return _fallback_provider
