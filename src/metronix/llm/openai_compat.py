"""Backward compatibility -- use metronix.llm.providers.custom instead.

The OpenAICompatProvider scaffold stub has been replaced by the full
provider implementations in metronix.llm.providers (DeepSeekProvider,
OpenRouterProvider, CustomProvider), all of which use OpenAI-compatible
API formats.
"""

from metronix.llm.providers.custom import CustomProvider as OpenAICompatProvider  # noqa: F401
