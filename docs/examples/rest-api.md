# REST API Example (curl)

Connect to Metronix Memory via REST API, check health, store a memory record, and retrieve it.

## Prerequisites

- `curl` (standard command-line tool)
- Metronix Memory server running on `http://localhost:8000`

## Example

```bash
# Health check
curl -X GET http://localhost:8000/health

# Store a memory record
curl -X POST http://localhost:8000/api/v1/memory/records \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "MTRNIX",
    "agent_id": "my-agent-001",
    "content": "User prefers detailed explanations",
    "kind": "preference"
  }'

# Retrieve memory records
curl -X GET "http://localhost:8000/api/v1/memory/records?workspace_id=MTRNIX&agent_id=my-agent-001"
```

## What to Expect

1. **Health check** returns `{"status": "ok"}` or similar
2. **Store** returns the created memory record with an ID and timestamp
3. **Retrieve** returns a list of memory records for that workspace and agent

## With Authentication (Production)

If authentication is enabled, add the Bearer token header to each request:

```bash
curl -X POST http://localhost:8000/api/v1/memory/records \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "MTRNIX",
    "agent_id": "my-agent-001",
    "content": "User prefers detailed explanations",
    "kind": "preference"
  }'
```

## Memory Record Kinds

Valid values for `kind`:
- `"fact"` — static information
- `"preference"` — user/agent preferences
- `"pinned"` — high-priority or frequently-accessed memory
