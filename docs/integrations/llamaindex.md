# LlamaIndex

Use Metronix Memory as the retrieval and durable-memory backend for a LlamaIndex
workflow — a custom `BaseRetriever` and the `metronix_memory_*` tools via MCP, or a
grounded chat step via `/v1` — instead of building a second local index over data
Metronix already owns.

> **MCP authentication mode:** Local `AUTH_ENABLED=false` MCP examples use
> `METRONIX_MCP_API_KEY` for the transport. Hosted `AUTH_ENABLED=true` MCP clients use a
> user JWT instead; the shared key is ignored. **Exception, verified by running this
> guide's example:** the `metronix_memory_*` tools require an authenticated *principal*
> and reject the shared `METRONIX_MCP_API_KEY` with `AUTH_REQUIRED` in **both** modes —
> use a personal API key (`mtk_…`) or a JWT for them. `metronix_search_fast` accepts
> either.

## Prerequisites

- Metronix Memory running and accessible (`curl http://localhost:8000/health` returns OK)
- Python 3.10+ (`llama-index-core` requires `>=3.10,<4`)
- Install the client packages **in a separate environment from the Metronix backend**:
  ```bash
  pip install \
    "llama-index-core>=0.14,<0.15" \
    "llama-index-tools-mcp>=0.5,<0.6" \
    "llama-index-llms-openai-like>=0.7,<0.8"
  ```
  Verified current as of this guide: `llama-index-core` 0.14.24,
  `llama-index-tools-mcp` 0.5.1, `llama-index-llms-openai-like` 0.7.2.
  `llama-index-tools-mcp` depends on `mcp>=2.0,<3` — the **same** major line Metronix
  pins — so there is no forced-downgrade conflict (unlike `langchain-mcp-adapters`; see
  the [LangGraph guide](langgraph.md)). A separate venv is still the right call: LlamaIndex
  pulls a large dependency tree that has no reason to share the server's environment.
- A **personal API key** (`mtk_…`) for the memory tools — see Setup step 2. The shared
  `METRONIX_MCP_API_KEY` does not work for `metronix_memory_*` (see the callout above).
- `METRONIX_OPENAI_COMPAT_KEY` for the `/v1` LLM used to synthesize answers.

## When to use which surface

| Goal | Surface | Shape |
| --- | --- | --- |
| Feed Metronix passages into a LlamaIndex query engine or agent | `metronix_search_fast` (MCP) wrapped in a `BaseRetriever` | raw ranked passages → `NodeWithScore` |
| Let the agent itself decide when to recall / persist durable memory | `metronix_memory_search` / `metronix_memory_store` (MCP) as `FunctionTool`s | per-agent memory records |
| Drop in one grounded, cited chat step | `/v1/chat/completions` via `OpenAILike` | full hybrid RAG → text with a sources footer |

`metronix_search_fast` is **dense + metadata** recall, tuned for low latency. The full
hybrid pipeline — dense + sparse/SPLADE, graph enrichment, reranking, freshness — runs
behind `/v1/chat/completions`. The example below uses the fast tool for retrieval and
points the query engine's LLM at `/v1`, so the synthesized answer still benefits from the
full pipeline.

## Metronix hybrid retrieval vs. a local vector index

A default LlamaIndex `VectorStoreIndex` is a single-vector store you build and own:

| | Local `VectorStoreIndex` | Metronix backend |
| --- | --- | --- |
| Retrieval | dense cosine top-k; add BM25 / rerank / fusion yourself | dense + sparse/SPLADE + graph + RRF (adaptive *k*) + reranker + freshness, server-side |
| Ingestion | you: readers → chunking → embedding model → vector store | connectors sync Jira/Confluence/Notion/GitHub/GDrive incrementally |
| Freshness | you re-index; anything after the build is invisible | scheduled sync + a freshness-review layer flags stale docs |
| Boundaries | in-process / your store | workspace isolation, auth, audit, RAG traces |
| Memory across sessions | none (an index is not memory) | a separate durable agent-memory layer with scopes and lifecycle |
| First-run cost | high — the whole pipeline is yours | low — an HTTP call |
| Control | full: custom chunking, your embedder, offline eval, air-gapped | the pipeline is a service (tuned via server-side env) |

**Use a local index** for a fixed corpus you control, task-specific chunking,
reproducible offline eval, air-gapped data, or a one-off document a user dropped into a
session that isn't worth syncing.

**Use Metronix** for multi-source knowledge that changes, knowledge shared across
agents or people, retrieval quality you don't want to build, or durable memory that must
survive across sessions.

**Together:** a local index over the ephemeral working set plus a Metronix-backed
retriever over the org knowledge, merged with `QueryFusionRetriever` or a router. Don't
rebuild a local index over data Metronix already syncs — query Metronix.

## Setup

1. Get the backend running (see the [main README](../../README.md)) and confirm
   `curl http://localhost:8000/health` returns `{"status":"ok"}`.
2. Mint a **personal API key** — the credential the memory tools accept. Locally
   (`AUTH_ENABLED=false`), any request is trusted as admin, so no login is needed:
   ```bash
   curl -X POST http://localhost:8000/api/v1/users \
     -H "Content-Type: application/json" \
     -d '{"email":"llamaindex-demo@example.com","password":"<a-strong-password>","role":"admin"}'
   # -> {"...", "api_key": "mtk_..."}   <- export as METRONIX_MCP_TOKEN
   ```
   Hosted (`AUTH_ENABLED=true`): log in via `/api/v1/auth/login` for a JWT, or have an
   admin issue a personal key via `POST /api/v1/users/{user_id}/api-keys`. That key/JWT
   is sufficient on its own only if the underlying user is an **admin**. A non-admin
   principal also needs an active grant for the exact `(workspace_id, agent_id)` pair or
   every `metronix_memory_*` call fails closed with `AUTH_REQUIRED`; creating an agent
   does not grant its creator access, and there is currently no public provisioning path
   for that grant — so use admin credentials for a hosted setup.
3. Connect a `BasicMCPClient` with your headers and hand its tools to LlamaIndex:
   ```python
   from llama_index.tools.mcp import BasicMCPClient, aget_tools_from_mcp_url

   client = BasicMCPClient(
       "http://localhost:8000/mcp",  # streamable-HTTP; a /sse path would switch transport
       headers={
           "Authorization": f"Bearer {METRONIX_MCP_TOKEN}",
           "X-Agent-Id": "llamaindex-demo-agent",  # keep this stable per agent
       },
   )
   tools = await aget_tools_from_mcp_url(
       "http://localhost:8000/mcp",
       client=client,  # without this it builds an UNauthenticated client
       allowed_tools=["metronix_search_fast", "metronix_memory_search", "metronix_memory_store"],
   )
   ```
   Pre-bind the workspace and agent so the LLM never has to supply them:
   ```python
   from llama_index.tools.mcp import McpToolSpec

   spec = McpToolSpec(
       client,
       allowed_tools=["metronix_memory_search", "metronix_memory_store"],
       global_partial_params={"workspace_id": "MTRNIX", "agent_id": "llamaindex-demo-agent"},
   )
   tools = await spec.to_tool_list_async()
   ```
4. For a retrieval **backend** (not just agent tools), wrap `metronix_search_fast` in a
   `BaseRetriever` and feed a `RetrieverQueryEngine` — see
   [`examples/llamaindex_metronix_example.py`](../../examples/llamaindex_metronix_example.py)
   for a full retriever + memory round-trip using a stable `agent_id` and
   `workspace_id="MTRNIX"`.
5. One adapter detail worth knowing before you write a tool wrapper:
   `client.call_tool(...)` resolves to the raw MCP `CallToolResult`, not a parsed dict.
   Metronix returns the tool's JSON as the **`.text` of the first content block**
   (`result.content[0].text`) — `result.structuredContent` is `None`. Calling
   `.get("results")` on the `CallToolResult` itself silently no-ops — easy to misread as
   "zero results". The example wraps the unwrapping in a `_mcp_json()` helper (it still
   checks `structuredContent` first, so it keeps working if a future server version adds
   it).

## Verify

After setup, confirm the connection works:

1. `curl http://localhost:8000/health` returns a 200.
2. Seed a couple of KB documents so the retriever has something to return:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/knowledge/store?workspace_id=MTRNIX" \
     -H "Authorization: Bearer $METRONIX_MCP_TOKEN" -H "Content-Type: application/json" \
     -d '{"content":"Metronix hybrid retrieval fuses dense vectors, SPLADE sparse terms, and a knowledge graph, then combines the channels with reciprocal rank fusion and an adaptive k.","title":"Retrieval overview","source_type":"note"}'

   curl -X POST "http://localhost:8000/api/v1/knowledge/store?workspace_id=MTRNIX" \
     -H "Authorization: Bearer $METRONIX_MCP_TOKEN" -H "Content-Type: application/json" \
     -d '{"content":"metronix_search_fast is dense + metadata recall tuned for low latency; the full hybrid pipeline with reranking and freshness runs behind /v1/chat/completions.","title":"search_fast vs full pipeline","source_type":"note"}'
   ```
   `doc_label` is the citation key that always comes back. A retrieved node also carries a
   `url` **when its source has one** — connector-synced documents (Jira/Confluence/GitHub/…)
   do; a document you store by hand through this endpoint currently retrieves with an empty
   `url` (its `metadata.url`, if you pass one, is kept on the stored document but not yet
   surfaced on the retrieved chunk).
3. Run `python examples/llamaindex_metronix_example.py "What does Metronix use for hybrid retrieval?"`.
   The query engine owns the single retrieval; the script then lists the answer's
   own `source_nodes` under `[retrieve]` — each with its `doc_label` (and `url`,
   shown as `url=-` for the hand-seeded docs above) — followed by an `[answer]`
   block synthesized through `/v1` and `memory round-trip: ok` — the fact stored via
   `metronix_memory_store` is found again by `metronix_memory_search` in the same run.
   The script exits `0` only when both passes succeed; a zero-node retrieval (KB not
   seeded / wrong `workspace_id`) or a failed memory round-trip prints
   `verification FAILED` and exits non-zero, so it is safe to gate a shell or CI check on.
4. Alternatively, call `await client.list_tools()` and confirm `metronix_search_fast`,
   `metronix_memory_search`, and `metronix_memory_store` appear.

## Troubleshooting

**Connection refused:** Verify the stack is running (`curl http://localhost:8000/health`).

**`AUTH_REQUIRED` from `metronix_memory_search` / `metronix_memory_store` (but
`metronix_search_fast` works):** you're using the shared `METRONIX_MCP_API_KEY`. It
authenticates the MCP transport but never binds a principal, and every `metronix_memory_*`
tool requires one. Swap in a personal API key (`mtk_…`, Setup step 2) or a JWT — sufficient
alone only for an **admin** user; a non-admin also needs a `(workspace_id, agent_id)`
grant, which has no public provisioning path today, so use admin credentials for hosted.

**Retriever returns zero nodes:** the workspace has nothing indexed yet, or you queried
the wrong `workspace_id`. Seed a document (Verify step 2) or run a connector sync first.

**Retrieved nodes have an empty `url`:** expected for documents stored by hand through
`POST /api/v1/knowledge/store` / `metronix_store` — the retrieval layer surfaces `url`
only for connector-synced sources today. `doc_label` is always populated; use it as the
citation key. Cite by `url` only when you know the corpus is connector-synced.

**Tool result looks empty / `.get(...)` returns nothing:** you're calling `.get()` on the
`CallToolResult` object. Parse the first content block's `.text` (`result.content[0].text`)
with `json.loads` first — Metronix leaves `result.structuredContent` `None`. See Setup step 5.

**`BasicMCPClient` opens an SSE connection instead of streamable HTTP:** the URL path ends
in `/sse` or carries `?transport=sse`. Metronix's endpoint is `/mcp` (streamable HTTP);
pass it without an `/sse` suffix.

**`RuntimeError: asyncio ...` from `client.call_tool` in a sync script:**
`BasicMCPClient` is async-only. Call it inside `asyncio.run(...)`, or go through the
query engine's `aquery()` (or the retriever's own `aretrieve()`) as the example does.

**Authentication errors on `/v1` (the answer step):** confirm `METRONIX_OPENAI_COMPAT_KEY`
matches `.env` and the model id is `metronix-rag-<workspace_id>` (`metronix-rag-MTRNIX` by
default).

## Recommendation

Retrieval-centric workflow — Metronix passages into a LlamaIndex query engine? Wrap
`metronix_search_fast` in a `BaseRetriever` (the example's first pass).
An agent that decides for itself when to recall or persist? Load `metronix_memory_search`
/ `metronix_memory_store` as `FunctionTool`s with `global_partial_params`.
Just need one grounded chat step? Point `OpenAILike` at `/v1` and skip the retriever.
