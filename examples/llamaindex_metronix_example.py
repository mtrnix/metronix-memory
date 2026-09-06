#!/usr/bin/env python3
"""
LlamaIndex example: Metronix as a retrieval backend and durable memory, over MCP.

Demonstrates the pattern from docs/integrations/llamaindex.md in two passes:

  1. Retrieval -- MetronixRetriever (a custom llama_index BaseRetriever) calls
     the `metronix_search_fast` MCP tool and returns server-ranked knowledge-base
     passages as NodeWithScore. A RetrieverQueryEngine then synthesizes a cited
     answer with an OpenAI-compatible LLM pointed at Metronix's own /v1 endpoint.
     There is no local VectorStoreIndex and no embedding model in this process --
     the corpus, the ranking, and its freshness all live in Metronix.

  2. Memory -- metronix_memory_store persists a fact, then metronix_memory_search
     retrieves it back in the same run.

This is an MCP *client* example. Install its dependencies in a separate
environment from the Metronix backend itself (llama-index pulls a large
dependency tree; keeping it out of the server venv avoids surprises). Unlike
langchain-mcp-adapters, llama-index-tools-mcp tracks the same major `mcp`
release as Metronix (>=2,<3), so there is no forced-downgrade conflict.

Prerequisites:
    pip install \\
        "llama-index-core>=0.14,<0.15" \\
        "llama-index-tools-mcp>=0.5,<0.6" \\
        "llama-index-llms-openai-like>=0.7,<0.8"

    Get a PERSONAL API key (mtk_...), not the shared METRONIX_MCP_API_KEY -- the
    shared key authenticates the MCP transport but never binds a principal, and
    the metronix_memory_* tools reject it with AUTH_REQUIRED (metronix_search_fast
    works with either). Locally (AUTH_ENABLED=false) any caller is trusted as
    admin, so no login step is needed:
        curl -X POST http://localhost:8000/api/v1/users \\
          -H "Content-Type: application/json" \\
          -d '{"email":"llamaindex-demo@example.com",
               "password":"<a-strong-password>","role":"admin"}'
        # -> {"...", "api_key": "mtk_..."}
    export METRONIX_MCP_TOKEN=mtk_...
    export METRONIX_OPENAI_COMPAT_KEY=metronix-test-key   # matches .env

    Seed a couple of KB documents so the retriever has something to return
    (see the "Verify" section of the guide for the exact commands).

Usage:
    python examples/llamaindex_metronix_example.py "What does Metronix use for retrieval?"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from llama_index.core import QueryBundle, get_response_synthesizer
from llama_index.core.async_utils import asyncio_run
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.llms.openai_like import OpenAILike
from llama_index.tools.mcp import BasicMCPClient

METRONIX_URL = os.environ.get("METRONIX_URL", "http://localhost:8000")
METRONIX_MCP_TOKEN = os.environ.get("METRONIX_MCP_TOKEN", "")  # personal mtk_ key
METRONIX_OPENAI_COMPAT_KEY = os.environ.get("METRONIX_OPENAI_COMPAT_KEY", "metronix-test-key")
AGENT_ID = "llamaindex-demo-agent"  # stable id, reused across retrieve and store
WORKSPACE_ID = "MTRNIX"


def _mcp_json(result: Any) -> dict[str, Any]:
    """Unwrap an MCP tool call result into the plain dict Metronix returned.

    llama-index-tools-mcp hands back the raw MCP ``CallToolResult``. Metronix
    returns the tool's JSON payload as the ``text`` of the first content block;
    ``structuredContent`` is ``None``. The ``structuredContent`` branch below is
    kept only so this keeps working if a future server version populates it.
    Calling ``.get(...)`` on the ``CallToolResult`` itself silently misses --
    which reads like "zero results" rather than a parsing bug.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        # FastMCP wraps non-object returns as {"result": ...}; unwrap that.
        payload = structured.get("result", structured) if "result" in structured else structured
    else:
        payload = None
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if text:
                payload = json.loads(text)
                break
        if payload is None:
            raise TypeError(f"Unexpected MCP tool result shape: {result!r}")

    # Metronix tools report failures as {"error": {"code", "message", ...}} with
    # an HTTP 200 -- surface it instead of letting `.get("results", [])` read as
    # an empty (but successful) result.
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        raise RuntimeError(f"{err.get('code', 'ERROR')}: {err.get('message', err)}")
    return payload


class MetronixRetriever(BaseRetriever):
    """A llama_index retriever backed by the Metronix ``metronix_search_fast`` tool.

    Returns Metronix's server-ranked KB passages as nodes. This is dense + metadata
    recall (the low-latency tool); the full hybrid pipeline -- sparse/SPLADE, graph
    enrichment, reranking, freshness -- runs behind the /v1 chat endpoint, which the
    query engine below uses as its LLM.
    """

    def __init__(
        self,
        client: BasicMCPClient,
        *,
        workspace_id: str = WORKSPACE_ID,
        top_k: int = 5,
    ) -> None:
        self._client = client
        self._workspace_id = workspace_id
        self._top_k = top_k
        super().__init__()

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        raw = await self._client.call_tool(
            "metronix_search_fast",
            {
                "query": query_bundle.query_str,
                "workspace_id": self._workspace_id,
                "top_k": self._top_k,
            },
        )
        payload = _mcp_json(raw)
        nodes: list[NodeWithScore] = []
        for hit in payload.get("results", []):
            # doc_label is always set and is the stable citation key. url is
            # populated for connector-synced sources (Jira/Confluence/GitHub/...);
            # a hand-stored KB doc currently comes back with an empty url.
            node = TextNode(
                text=hit.get("content", ""),
                id_=hit.get("doc_label") or None,
                metadata={
                    "doc_label": hit.get("doc_label", ""),
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "source_type": hit.get("source_type", ""),
                    "date": hit.get("date", ""),
                },
            )
            nodes.append(NodeWithScore(node=node, score=float(hit.get("score", 0.0))))
        return nodes

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        # BaseRetriever requires the sync entrypoint; bridge to the async impl
        # (asyncio_run handles being called from inside a running loop).
        return asyncio_run(self._aretrieve(query_bundle))


def _build_client() -> BasicMCPClient:
    # `headers` is forwarded to the streamable-HTTP transport (Metronix's /mcp).
    # A URL path ending in /sse would switch BasicMCPClient to SSE instead.
    return BasicMCPClient(
        f"{METRONIX_URL}/mcp",
        headers={
            "Authorization": f"Bearer {METRONIX_MCP_TOKEN}",
            "X-Agent-Id": AGENT_ID,
        },
    )


async def retrieval_pass(client: BasicMCPClient, question: str) -> int:
    """Pass 1: answer ``question`` from Metronix-retrieved KB passages.

    The ``RetrieverQueryEngine`` owns the one and only retrieval call. The nodes
    listed below are read back off the response (``source_nodes``) -- the exact
    passages the answer was grounded on -- rather than from a second, separate
    ``metronix_search_fast`` request whose ranking could drift from them
    (toomij99, PR #439).
    """
    retriever = MetronixRetriever(client, top_k=5)
    llm = OpenAILike(
        model=f"metronix-rag-{WORKSPACE_ID}",
        api_base=f"{METRONIX_URL}/v1",
        api_key=METRONIX_OPENAI_COMPAT_KEY,
        is_chat_model=True,
        context_window=8192,
    )
    engine = RetrieverQueryEngine(
        retriever=retriever,
        response_synthesizer=get_response_synthesizer(llm=llm),
    )
    answer = await engine.aquery(question)
    nodes = answer.source_nodes

    print(f"\n[retrieve] {len(nodes)} node(s) for {question!r}")
    for n in nodes:
        md = n.node.metadata
        print(
            f"  - {md.get('doc_label') or '(no doc_label)'}"
            f"  score={n.score:.3f}"
            f"  url={md.get('url') or '-'}"
        )
    if not nodes:
        print("  nothing indexed yet -- seed a few KB docs first (see the guide's Verify step)")
        return 0

    print(f"\n[answer]\n{answer}")
    return len(nodes)


async def memory_pass(client: BasicMCPClient, fact: str) -> bool:
    """Pass 2: store a durable memory record, then search it back."""
    stored = _mcp_json(
        await client.call_tool(
            "metronix_memory_store",
            {
                "content": fact,
                "agent_id": AGENT_ID,
                "workspace_id": WORKSPACE_ID,
                "kind": "fact",
            },
        )
    )
    print(f"\n[memory.store] id={stored.get('id')} deduped={stored.get('deduped')}")

    found = _mcp_json(
        await client.call_tool(
            "metronix_memory_search",
            {
                "query": fact,
                "agent_id": AGENT_ID,
                "workspace_id": WORKSPACE_ID,
                "top_k": 5,
            },
        )
    )
    hits = found.get("results", [])
    print(f"[memory.search] {len(hits)} hit(s)")
    for h in hits:
        rec = h["record"]
        print(f"  - {rec['id']}  score={h['score']:.3f}  {rec['content'][:70]!r}")

    retrieved = any(h["record"]["id"] == stored.get("id") for h in hits)
    print(f"[memory] stored fact retrieved back: {retrieved}")
    return retrieved


def _verification_failures(node_count: int, memory_retrieved: bool) -> list[str]:
    """Names of the verification passes that did not meet the guide's bar.

    An empty list means the run passed. This script doubles as the guide's
    "Verify" step, whose Setup seeds a couple of KB docs *before* you run it, so
    a zero-node retrieval here is a real failure -- not an empty-corpus edge
    case -- and must surface as a non-zero exit for a shell/CI caller.
    """
    failures: list[str] = []
    if node_count <= 0:
        failures.append("retrieval returned no nodes (seed KB docs -- guide Setup step 2)")
    if not memory_retrieved:
        failures.append("memory round-trip did not return the stored fact")
    return failures


async def main() -> None:
    if not METRONIX_MCP_TOKEN:
        print("Set METRONIX_MCP_TOKEN to a PERSONAL api key (mtk_...) -- see the module")
        print("docstring. The shared METRONIX_MCP_API_KEY will not work for the memory")
        print("tools (AUTH_REQUIRED).")
        sys.exit(1)

    question = sys.argv[1] if len(sys.argv) > 1 else "What does Metronix use for hybrid retrieval?"
    client = _build_client()

    node_count = await retrieval_pass(client, question)
    retrieved = await memory_pass(client, f"LlamaIndex demo note: {question}")

    failures = _verification_failures(node_count, retrieved)
    print("\n--- summary ---")
    print(f"retrieval nodes:        {node_count}")
    print(f"memory round-trip:      {'ok' if retrieved else 'FAILED'}")
    if failures:
        print("\nverification FAILED:")
        for reason in failures:
            print(f"  - {reason}")
        print("\nCheck METRONIX_MCP_TOKEN is a personal mtk_ key and the KB is seeded.")
        sys.exit(1)
    print("verification:           ok")


if __name__ == "__main__":
    asyncio.run(main())
