"""Health checks — verify connectivity to all backing services.

Used by GET /health and GET /ready endpoints.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


class HealthChecker:
    """Checks connectivity to PostgreSQL, Qdrant, Neo4j, and Ollama.

    Returns a dict of service → status for the health API.
    """

    def __init__(
        self,
        postgres_dsn: str = "",
        qdrant_host: str = "",
        qdrant_port: int = 6333,
        neo4j_uri: str = "",
        ollama_host: str = "",
    ) -> None:
        self._postgres_dsn = postgres_dsn
        self._qdrant_host = qdrant_host
        self._qdrant_port = qdrant_port
        self._neo4j_uri = neo4j_uri
        self._ollama_host = ollama_host

    async def check_all(self) -> dict[str, dict[str, str]]:
        """Check all services and return status map.

        Returns:
            Dict like {"postgres": {"status": "ok"}, "qdrant": {"status": "error", "detail": "..."}}.
        """  # noqa: E501
        logger.info("health.check_all")
        results: dict[str, dict[str, str]] = {}

        results["postgres"] = await self._check_postgres()
        results["qdrant"] = await self._check_qdrant()
        results["neo4j"] = await self._check_neo4j()
        results["ollama"] = await self._check_ollama()

        return results

    async def _check_postgres(self) -> dict[str, str]:
        """Ping PostgreSQL."""
        # TODO: implement
        # asyncpg.connect(self._postgres_dsn) → SELECT 1
        return {"status": "not_configured" if not self._postgres_dsn else "unchecked"}

    async def _check_qdrant(self) -> dict[str, str]:
        """Ping Qdrant HTTP API."""
        # TODO: implement
        # httpx.get(f"http://{host}:{port}/healthz")
        return {"status": "not_configured" if not self._qdrant_host else "unchecked"}

    async def _check_neo4j(self) -> dict[str, str]:
        """Ping Neo4j via bolt."""
        # TODO: implement
        # neo4j.AsyncGraphDatabase.driver(uri) → session.run("RETURN 1")
        return {"status": "not_configured" if not self._neo4j_uri else "unchecked"}

    async def _check_ollama(self) -> dict[str, str]:
        """Ping Ollama API."""
        # TODO: implement
        # httpx.get(f"{host}/api/tags")
        return {"status": "not_configured" if not self._ollama_host else "unchecked"}
