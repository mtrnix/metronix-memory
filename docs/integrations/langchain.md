# LangChain

> **MCP authentication mode:** Local `AUTH_ENABLED=false` MCP examples use
> `METRONIX_MCP_API_KEY`. Hosted `AUTH_ENABLED=true` MCP clients use a user JWT instead;
> the shared key is ignored. **Exception:** every `metronix_memory_*` tool
> (`metronix_memory_search`, `metronix_memory_store`, `metronix_memory_list`, …) requires
> an authenticated *principal* and rejects the shared `METRONIX_MCP_API_KEY` with
> `AUTH_REQUIRED` in **both** modes — use a personal API key (`mtk_…`) or a JWT for those.
> `metronix_status` and `metronix_search_fast` accept either. See
> [Credential for the memory tools](#credential-for-the-memory-tools).

## Recommended mode

Use Metronix Memory's OpenAI-compatible API for chat, or call REST/MCP directly for advanced
memory workflows.

## Chat setup

Use:

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

This gives LangChain a RAG-backed chat surface over your Metronix Memory workspace.

## When to use MCP too

Use MCP if you want explicit tools for:

- memory store and search
- source sync
- status checks
- low-level retrieval flows

The `metronix_memory_*` tools (memory store and search) need a personal API key (`mtk_…`)
or a user JWT — not the shared `METRONIX_MCP_API_KEY`. See below.

## Credential for the memory tools

`METRONIX_MCP_API_KEY` authenticates the MCP transport but binds no request principal, so
every `metronix_memory_*` tool rejects it with `AUTH_REQUIRED: unauthorized agent memory
access` — in **both** `AUTH_ENABLED` modes. `metronix_status` and `metronix_search_fast`
have no ownership check and keep working with it, so the connection looks fully working
right up until the first memory call.

Use a **personal API key** (`mtk_…`) or a user JWT for `metronix_memory_*`. Locally
(`AUTH_ENABLED=false`), any request is trusted as admin, so this works with no login step:

```bash
curl -X POST http://localhost:8000/api/v1/users \
  -H "Content-Type: application/json" \
  -d '{"email":"langchain-agent@example.com","password":"<a-strong-password>","role":"admin"}'
# -> {"...", "api_key": "mtk_..."}   <- use as the MCP Bearer token
```

Hosted (`AUTH_ENABLED=true`): log in via `/api/v1/auth/login` for a JWT, or have an admin
issue a personal key via `POST /api/v1/users/{user_id}/api-keys`. That personal key/JWT is
necessary but, on its own, only sufficient if the underlying user is an **admin**. A
non-admin principal additionally needs an active grant for the exact
`(workspace_id, agent_id)` pair it's calling with, or every `metronix_memory_*` call fails
closed with `AUTH_REQUIRED`. Creating an agent does **not** grant its creator access —
only agents that already existed when grant support shipped (migration
`032_agent_access_grants`) were backfilled with one. There is currently no public way to
provision this grant for a new agent, so for a hosted setup, use admin credentials.

## Verify

After setup, confirm the connection works:

1. Point your `ChatOpenAI` (or equivalent) client at `http://localhost:8000/v1` with model `metronix-rag-<workspace_id>`.
2. Send a test message and confirm a grounded response is returned.
3. If using MCP, call `metronix_status(workspace_id="MTRNIX")` and confirm a status response.
4. For the `metronix_memory_*` tools, call `metronix_memory_list` with your personal
   `mtk_…` key or JWT — a successful `metronix_status` with the shared key does **not**
   mean the memory tools will work.

If the endpoint is unreachable, run `curl http://localhost:8000/health` to check the stack.

## Troubleshooting

**API endpoint unreachable:** Verify the stack is running (`curl http://localhost:8000/health`) and that `METRONIX_OPENAI_COMPAT_KEY` in your `.env` is set and non-empty.

**MCP tools not available:** If using MCP, check that `METRONIX_MCP_API_KEY` is set and the `Authorization: Bearer <key>` header is included in all MCP requests.

**`AUTH_REQUIRED: unauthorized agent memory access` from a `metronix_memory_*` call (but `metronix_status` / `metronix_search_fast` work with the same key):** you're using the shared `METRONIX_MCP_API_KEY`. It authenticates the MCP *transport* but never binds a request principal, and every `metronix_memory_*` tool requires one (`require_agent_access` in `mcp/tools/_agent_access.py`). Swap in a personal API key (`mtk_…`) or a JWT — but that alone is only enough if the underlying user is an **admin**. A non-admin principal also needs an active grant for the exact `(workspace_id, agent_id)` pair, which today has no public provisioning path, so use admin credentials for hosted setups. See [Credential for the memory tools](#credential-for-the-memory-tools).

**Authentication errors:** Confirm the API key passed to LangChain matches `METRONIX_OPENAI_COMPAT_KEY` in `.env`.

## Recommendation

For a first integration:

1. Use the OpenAI-compatible endpoint for `ChatOpenAI` style flows.
2. Add MCP or REST later if you need durable memory control outside chat.

That keeps the first version simple and avoids building a tiny distributed system by accident.
