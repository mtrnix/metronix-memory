"""Metronix MCP HTTP client for LongMemEval benchmark ingestion and search."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MCP_TIMEOUT = httpx.Timeout(60.0, read=300.0)


def _parse_tool_payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    content = getattr(result, "content", None)
    if not content:
        return {}
    for block in content:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {"text": text}
    return {}


def _raise_tool_error(payload: dict[str, Any]) -> None:
    if "error" not in payload:
        return
    error = payload["error"]
    if isinstance(error, dict):
        raise RuntimeError(error.get("message", str(error)))
    raise RuntimeError(str(error))


class MetronixMCPClient:
    """MCP client that reuses one HTTP session per question."""

    def __init__(
        self,
        *,
        mcp_url: str,
        api_key: str,
        workspace_id: str,
        agent_id: str,
    ) -> None:
        self.mcp_url = mcp_url.rstrip("/")
        self.api_key = api_key
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Agent-Id": agent_id,
        }

    def ingest_and_search(
        self,
        *,
        sessions: list[list[dict]],
        dates: list[str],
        format_session_text,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Ingest haystack sessions and search memory in one MCP session."""
        return asyncio.run(
            self._ingest_and_search_async(
                sessions=sessions,
                dates=dates,
                format_session_text=format_session_text,
                query=query,
                top_k=top_k,
            )
        )

    async def _ingest_and_search_async(
        self,
        *,
        sessions: list[list[dict]],
        dates: list[str],
        format_session_text,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise ImportError(
                "MCP SDK not installed. Run: pip install -r requirements-bench.txt"
            ) from exc

        async with (
            httpx.AsyncClient(
                headers=self._headers,
                trust_env=False,
                follow_redirects=True,
                timeout=MCP_TIMEOUT,
            ) as http_client,
            streamable_http_client(
                self.mcp_url,
                http_client=http_client,
            ) as streams,
        ):
            read_stream, write_stream, _ = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                for idx, (session_turns, date) in enumerate(zip(sessions, dates, strict=False)):
                    text = format_session_text(session_turns, date=date)
                    await self._memory_store(session, text, session_idx=idx, date=date)

                payload = await self._memory_search(session, query=query, top_k=top_k)
                results = payload.get("results", [])
                return results if isinstance(results, list) else []

    async def _memory_store(
        self,
        session: Any,
        content: str,
        *,
        session_idx: int,
        date: str,
        kind: str = "fact",
        source_type: str = "longmemeval",
        importance_score: float = 0.7,
    ) -> dict[str, Any]:
        result = await session.call_tool(
            "metronix_memory_store",
            {
                "content": content,
                "agent_id": self.agent_id,
                "workspace_id": self.workspace_id,
                "kind": kind,
                "source_type": source_type,
                "importance_score": importance_score,
                "tags": [f"session_{session_idx}", f"date_{date}"],
            },
        )
        payload = _parse_tool_payload(result)
        _raise_tool_error(payload)
        return payload

    async def _memory_search(
        self,
        session: Any,
        *,
        query: str,
        top_k: int,
    ) -> dict[str, Any]:
        result = await session.call_tool(
            "metronix_memory_search",
            {
                "query": query,
                "agent_id": self.agent_id,
                "workspace_id": self.workspace_id,
                "top_k": top_k,
            },
        )
        payload = _parse_tool_payload(result)
        _raise_tool_error(payload)
        return payload


class MetronixRestClient:
    """REST helpers for workspace preflight."""

    def __init__(self, *, api_url: str, timeout: float = 30.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.get(f"{self.api_url}/health")
            response.raise_for_status()
            return response.json()

    def list_workspaces(self) -> list[dict[str, Any]]:
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.get(f"{self.api_url}/api/v1/workspaces/")
            response.raise_for_status()
            payload = response.json()
            return payload.get("workspaces", [])

    def ensure_workspace(
        self,
        workspace_id: str,
        *,
        name: str = "LongMemEval benchmark",
        description: str = "Isolated workspace for agent-memory benchmarks",
    ) -> bool:
        existing = {ws.get("workspace_id") for ws in self.list_workspaces()}
        if workspace_id in existing:
            logger.info("Workspace %s already exists", workspace_id)
            return False
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.post(
                f"{self.api_url}/api/v1/workspaces/",
                json={
                    "workspace_id": workspace_id,
                    "name": name,
                    "description": description,
                },
            )
            response.raise_for_status()
            logger.info("Created workspace %s", workspace_id)
            return True
