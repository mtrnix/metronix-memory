# Python SDK Example (MCP)

> **Authentication mode:** this example calls `metronix_memory_store` and
> `metronix_memory_list`, which require an authenticated *principal*. The shared
> `METRONIX_MCP_API_KEY` authenticates the MCP transport but binds no principal, so those
> tools reject it with `AUTH_REQUIRED` in **both** `AUTH_ENABLED=false` and
> `AUTH_ENABLED=true` modes. Use a **personal API key** (`mtk_…`) or a user JWT in the
> Bearer header instead. (`metronix_status` and `metronix_search_fast` accept the shared
> key too, but the memory tools do not.)

Connect to Metronix Memory via MCP, store a memory record, and retrieve it.

## Prerequisites

- Python 3.8+
- `mcp` package: `pip install mcp`
- Metronix Memory server running on `http://localhost:8000`
- A **personal API key** (`mtk_…`) or a user JWT for the `metronix_memory_*` tools.
  Locally (`AUTH_ENABLED=false`), any request is trusted as admin, so this needs no login:
  ```bash
  curl -X POST http://localhost:8000/api/v1/users \
    -H "Content-Type: application/json" \
    -d '{"email":"sdk-example@example.com","password":"<a-strong-password>","role":"admin"}'
  # -> {"...", "api_key": "mtk_..."}
  ```
  Hosted (`AUTH_ENABLED=true`): log in via `/api/v1/auth/login` for a JWT, or have an
  admin issue a personal key via `POST /api/v1/users/{user_id}/api-keys`. The key/JWT is
  sufficient on its own only for an **admin** user; a non-admin principal also needs an
  active grant for the exact `(workspace_id, agent_id)` pair, which has no public
  provisioning path today — so use admin credentials for a hosted setup.

## Example

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    # Connect to Metronix Memory MCP endpoint.
    # "your-api-key" must be a personal API key (mtk_...) or a user JWT — NOT the shared
    # METRONIX_MCP_API_KEY, which metronix_memory_* reject with AUTH_REQUIRED.
    headers = {"Authorization": "Bearer your-api-key"}
    async with streamablehttp_client(
        "http://localhost:8000/mcp", headers=headers
    ) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            
            # Store a memory record
            store_result = await session.call_tool(
                "metronix_memory_store",
                {
                    "workspace_id": "MTRNIX",
                    "agent_id": "my-agent-001",
                    "content": "User prefers detailed explanations",
                    "kind": "preference"
                }
            )
            print("Stored:", store_result)
            
            # Retrieve memory records
            list_result = await session.call_tool(
                "metronix_memory_list",
                {
                    "workspace_id": "MTRNIX",
                    "agent_id": "my-agent-001",
                    "limit": 10
                }
            )
            print("Retrieved:", list_result)

asyncio.run(main())
```

## What to Expect

The script will:
1. Connect to the MCP endpoint and initialize the session
2. Store a memory record with `kind="preference"`
3. Retrieve the stored record(s) with a limit of 10 items

Output shows the stored memory and list of retrieved records as JSON/dict objects.

## Environment Variables

For security, set the credential as an environment variable — a personal API key
(`mtk_…`) or a user JWT, per the auth-mode note above:

```bash
export METRONIX_MCP_TOKEN="mtk_..."
```

Then update the headers line:
```python
import os
headers = {"Authorization": f"Bearer {os.getenv('METRONIX_MCP_TOKEN')}"}
```

## Troubleshooting

**`AUTH_REQUIRED: unauthorized agent memory access`:** you're using the shared
`METRONIX_MCP_API_KEY`. It authenticates the MCP transport but binds no request principal,
and every `metronix_memory_*` tool requires one (`require_agent_access` in
`mcp/tools/_agent_access.py`). Use a personal API key (`mtk_…`) or a JWT — sufficient
alone only for an **admin** user; a non-admin also needs a `(workspace_id, agent_id)`
grant, which has no public provisioning path today, so use admin credentials for hosted.
