# Python SDK Example (MCP)

Connect to Metronix Memory via MCP, store a memory record, and retrieve it.

## Prerequisites

- Python 3.8+
- `mcp` package: `pip install mcp`
- Metronix Memory server running on `http://localhost:8001`

## Example

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    # Connect to Metronix Memory MCP endpoint
    headers = {"Authorization": "Bearer your-api-key"}
    async with streamablehttp_client(
        "http://localhost:8001/mcp", headers=headers
    ) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            
            # Store a memory record
            store_result = await session.call_tool(
                "metatron_memory_store",
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
                "metatron_memory_list",
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

For security, set the API key as an environment variable:

```bash
export METATRON_MCP_API_KEY="your-api-key"
```

Then update the headers line:
```python
import os
headers = {"Authorization": f"Bearer {os.getenv('METATRON_MCP_API_KEY')}"}
```
