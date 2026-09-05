# JavaScript/TypeScript SDK

Call Metronix Memory from Node or a browser: OpenAI-compatible chat, REST, or MCP.

> **MCP authentication mode:** Local `AUTH_ENABLED=false` MCP examples use
> `METRONIX_MCP_API_KEY`. Hosted `AUTH_ENABLED=true` MCP clients use a user JWT instead;
> the shared key is ignored. **Exception:** every `metronix_memory_*` tool
> (`metronix_memory_search`, `metronix_memory_store`, `metronix_memory_list`, …) requires
> an authenticated *principal* and rejects the shared `METRONIX_MCP_API_KEY` with
> `AUTH_REQUIRED` in **both** modes — use a personal API key (`mtk_…`) or a JWT for those.
> `metronix_status` and `metronix_search_fast` accept either. See
> [Credential for the memory tools](#credential-for-the-memory-tools) and
> [Troubleshooting](#troubleshooting).

## Prerequisites

- Metronix Memory running and accessible (`curl http://localhost:8000/health` returns OK)
- Node.js 18+ for the REST/`/v1` examples below; **Node.js 20+** for the MCP example
  (`@modelcontextprotocol/client@2.0.0` requires it)
- The credential for whichever surface you're using: `METRONIX_OPENAI_COMPAT_KEY` for
  `/v1`; nothing extra for REST in local trusted mode (`AUTH_ENABLED=false`, the
  default) or a JWT/personal key in hosted mode; for MCP, `METRONIX_MCP_API_KEY` covers
  the transport and the non-memory tools (`metronix_status`, `metronix_search_fast`), but
  the `metronix_memory_*` tools need a personal API key (`mtk_…`) or a user JWT — see
  [Credential for the memory tools](#credential-for-the-memory-tools)

## Setup

1. Get the backend running (see the [main README](../../README.md)) and confirm
   `curl http://localhost:8000/health` returns `{"status":"ok"}`.
2. Set the credential(s) for the surface(s) you're using in `.env` — see Prerequisites.
3. For the MCP example, install the client:
   ```bash
   npm install @modelcontextprotocol/client
   ```

## Recommended surfaces

Pick the simplest interface that matches the job:

- OpenAI-compatible API for chat-style usage
- REST API for app integration
- MCP for tool-driven agent runtimes

## OpenAI-compatible values

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

## REST base URL

```text
http://localhost:8000/api/v1
```

## MCP values

```text
URL:            http://localhost:8000/mcp
Authorization:  Bearer <METRONIX_MCP_API_KEY>   # transport + non-memory tools; see below for metronix_memory_*
X-Agent-Id:     <stable-js-agent-id>
```

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
  -d '{"email":"js-agent@example.com","password":"<a-strong-password>","role":"admin"}'
# -> {"...", "api_key": "mtk_..."}   <- use as the MCP Bearer token (METRONIX_MCP_TOKEN below)
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

## Quickstart

Copy-paste examples for the three simplest calls. All three use the global `fetch` (Node
18+, or any browser) — no dependency needed until the MCP example below.

### Health check

```js
const res = await fetch('http://localhost:8000/health');
console.log(await res.json()); // { status: "ok" }
```

### Chat completion (`/v1`)

Runs hybrid RAG internally, not a raw LLM proxy. Always requires the OpenAI-compat key,
regardless of `AUTH_ENABLED`.

```js
const res = await fetch('http://localhost:8000/v1/chat/completions', {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${process.env.METRONIX_OPENAI_COMPAT_KEY}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    model: 'metronix-rag-default',
    messages: [{ role: 'user', content: 'What is in the backlog?' }],
    stream: false,
  }),
});
console.log(await res.json());
```

### Memory search (REST)

```js
const res = await fetch(
  'http://localhost:8000/api/v1/memory/search?workspace_id=default',
  {
    method: 'POST',
    headers: {
      // Only required when AUTH_ENABLED=true — see the auth-mode note above.
      Authorization: `Bearer ${process.env.METRONIX_TOKEN ?? ''}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      query: 'deployment preferences',
      agent_id: 'agent-abc',
      top_k: 5,
    }),
  },
);
console.log(await res.json());
```

## Using MCP instead

For tool-driven agent runtimes, use the official TypeScript SDK,
[`@modelcontextprotocol/client`](https://www.npmjs.com/package/@modelcontextprotocol/client)
(v2 — it replaces the older `@modelcontextprotocol/sdk` package; **requires Node.js
20+**, see Prerequisites). Install it as shown in Setup, then:

```ts
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';

// This example calls metronix_memory_store / metronix_memory_search, so METRONIX_MCP_TOKEN
// must be a personal API key (mtk_...) or a user JWT — NOT the shared METRONIX_MCP_API_KEY,
// which those tools reject with AUTH_REQUIRED in both auth modes. See "Credential for the
// memory tools" above.
const transport = new StreamableHTTPClientTransport(
  new URL('http://localhost:8000/mcp'),
  {
    requestInit: {
      headers: {
        Authorization: `Bearer ${process.env.METRONIX_MCP_TOKEN}`,
        'X-Agent-Id': 'js-quickstart-agent',
      },
    },
  },
);

const client = new Client({ name: 'metronix-js-quickstart', version: '1.0.0' });
await client.connect(transport); // runs the MCP initialize handshake

const stored = await client.callTool({
  name: 'metronix_memory_store',
  arguments: {
    content: 'User prefers dark mode',
    agent_id: 'js-quickstart-agent',
    workspace_id: 'MTRNIX',
    kind: 'preference',
  },
});
console.log('Stored:', stored.content);

const found = await client.callTool({
  name: 'metronix_memory_search',
  arguments: {
    query: 'dark mode',
    agent_id: 'js-quickstart-agent',
    workspace_id: 'MTRNIX',
  },
});
console.log('Found:', found.content);
```

## Verify

After setup, confirm the connection works:

1. Send a GET request to `http://localhost:8000/health` and confirm a 200 OK response.
2. For OpenAI-compatible usage, send a test chat completion request to `http://localhost:8000/v1/chat/completions` with the correct API key.
3. For MCP usage, call `metronix_status(workspace_id="MTRNIX")` and confirm a status response.
4. For the `metronix_memory_*` tools, call `metronix_memory_list` with your personal
   `mtk_…` key or JWT — a successful `metronix_status` with the shared key does **not**
   mean the memory tools will work.

## Troubleshooting

**Connection refused:** Verify the stack is running (`curl http://localhost:8000/health`).

**Authentication errors on `/v1`:** Confirm the API key passed matches `METRONIX_OPENAI_COMPAT_KEY` in `.env`.

**Authentication errors on `/mcp`:** In local mode (`AUTH_ENABLED=false`), confirm the `Authorization: Bearer <key>` header matches `METRONIX_MCP_API_KEY` in `.env`. In hosted mode (`AUTH_ENABLED=true`), the shared key is ignored — pass a user JWT instead. Either way, confirm `X-Agent-Id` is included in every request.

**`AUTH_REQUIRED: unauthorized agent memory access` from a `metronix_memory_*` call (but `metronix_status` / `metronix_search_fast` work with the same key):** you're using the shared `METRONIX_MCP_API_KEY`. It authenticates the MCP *transport* but never binds a request principal, and every `metronix_memory_*` tool requires one (`require_agent_access` in `mcp/tools/_agent_access.py`). Swap in a personal API key (`mtk_…`) or a JWT — but that alone is only enough if the underlying user is an **admin**. A non-admin principal also needs an active grant for the exact `(workspace_id, agent_id)` pair, which today has no public provisioning path, so use admin credentials for hosted setups. See [Credential for the memory tools](#credential-for-the-memory-tools).

**CORS errors calling `/v1` or `/api/v1` from a browser:** These endpoints are meant for server-side or same-origin calls. Don't ship `METRONIX_OPENAI_COMPAT_KEY` or a personal API key to browser code — proxy the request through your own backend instead.

## Recommendation

Writing a Node backend? Start with REST or `/v1`.
Building a browser frontend? Call your own backend, not Metronix directly — keep the API key server-side.
Wiring an autonomous agent on Node? Start with MCP via `@modelcontextprotocol/client`.
