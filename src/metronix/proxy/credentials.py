"""Resolve an upstream API key from the store, falling back to the env default."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metronix.storage.llm_upstream_credentials import LlmUpstreamCredentialsStore


class UpstreamCredentialsResolver:
    """Resolves api_key_ref -> plaintext key, with env-default fallback."""

    def __init__(self, store: LlmUpstreamCredentialsStore, *, default_key: str) -> None:
        self._store = store
        self._default_key = default_key

    async def resolve(self, api_key_ref: str | None, workspace_id: str) -> str:
        """Return a plaintext key. Stored key wins; else the env default."""
        if api_key_ref:
            key = await self._store.get_decrypted(api_key_ref, workspace_id)
            if key:
                return key
        return self._default_key
