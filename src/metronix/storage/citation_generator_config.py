"""Storage for workspace-scoped answer and citation generator overrides."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


CitationGeneratorProvider = Literal["ollama", "custom"]


@dataclass(frozen=True)
class CitationGeneratorOverride:
    """A workspace's explicit answer/citation generator configuration."""

    workspace_id: str
    provider: CitationGeneratorProvider
    model: str
    endpoint: str = ""
    credential_id: str | None = None
    updated_at: datetime | None = None


class CitationGeneratorConfigStore:
    """Async CRUD for ``citation_generator_configs``."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, workspace_id: str) -> CitationGeneratorOverride | None:
        query = text(
            """
            SELECT workspace_id, provider, model, endpoint, credential_id, updated_at
            FROM citation_generator_configs
            WHERE workspace_id = :workspace_id
            """
        )
        async with self._engine.begin() as conn:
            row = (await conn.execute(query, {"workspace_id": workspace_id})).mappings().first()
        if row is None:
            return None
        return CitationGeneratorOverride(
            workspace_id=str(row["workspace_id"]),
            provider=str(row["provider"]),  # type: ignore[arg-type]
            model=str(row["model"]),
            endpoint=str(row["endpoint"]),
            credential_id=str(row["credential_id"]) if row["credential_id"] else None,
            updated_at=row["updated_at"],
        )

    async def upsert(self, override: CitationGeneratorOverride) -> CitationGeneratorOverride:
        if override.provider not in {"ollama", "custom"}:
            raise ValueError("provider must be 'ollama' or 'custom'")
        if not override.model.strip():
            raise ValueError("model must not be empty")
        if override.provider == "custom" and not override.endpoint.strip():
            raise ValueError("custom provider requires an endpoint")
        if override.provider == "ollama" and override.endpoint:
            raise ValueError("ollama provider does not accept an endpoint")

        query = text(
            """
            INSERT INTO citation_generator_configs
                (workspace_id, provider, model, endpoint, credential_id)
            VALUES (:workspace_id, :provider, :model, :endpoint, :credential_id)
            ON CONFLICT (workspace_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                model = EXCLUDED.model,
                endpoint = EXCLUDED.endpoint,
                credential_id = EXCLUDED.credential_id,
                updated_at = NOW()
            """
        )
        values = {
            "workspace_id": override.workspace_id,
            "provider": override.provider,
            "model": override.model.strip(),
            "endpoint": override.endpoint.strip(),
            "credential_id": override.credential_id,
        }
        async with self._engine.begin() as conn:
            await conn.execute(query, values)
        saved = await self.get(override.workspace_id)
        if saved is None:
            raise RuntimeError("citation generator configuration was not saved")
        return saved

    async def delete(self, workspace_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM citation_generator_configs WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            )
        return result.rowcount > 0
