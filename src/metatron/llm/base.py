"""Base classes and types for LLM provider abstraction.

Defines the exception hierarchy, response/message dataclasses,
and the abstract LLMProvider base class that all providers implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base exception for LLM-related errors."""
    pass


class LLMConnectionError(LLMError):
    """Raised when connection to LLM provider fails."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when rate limit is exceeded."""
    pass


class LLMAuthenticationError(LLMError):
    """Raised when authentication fails."""
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str
    model: str
    provider: str
    usage: Dict[str, int] = field(default_factory=dict)
    raw_response: Optional[Dict[str, Any]] = None

    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0)

    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)


@dataclass
class Message:
    """Chat message."""

    role: str  # "system", "user", "assistant"
    content: str


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str = "base"

    def __init__(self, model: Optional[str] = None, **kwargs: Any) -> None:
        """Initialize the provider.

        Args:
            model: Model name to use (provider-specific).
            **kwargs: Additional provider-specific configuration.
        """
        self.model = model or self.default_model
        self.config = kwargs

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider."""
        pass

    @abstractmethod
    def chat_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        timeout: int = 60,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of messages in the conversation.
            temperature: Sampling temperature (0-2).
            max_tokens: Maximum tokens in response.
            json_mode: Request JSON output format.
            timeout: Request timeout in seconds.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with the model's response.

        Raises:
            LLMConnectionError: If connection fails.
            LLMRateLimitError: If rate limit is exceeded.
            LLMAuthenticationError: If authentication fails.
            LLMError: For other errors.
        """
        pass  # TODO: async migration

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is properly configured and available."""
        pass

    def _messages_to_dicts(self, messages: List[Message]) -> List[Dict[str, str]]:
        """Convert Message objects to dicts for API calls."""
        return [{"role": m.role, "content": m.content} for m in messages]
