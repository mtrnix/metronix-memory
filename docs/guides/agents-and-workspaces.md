# Agents And Workspaces

Metronix scopes data by workspace and, for memory, by agent.

## Workspace

A workspace groups documents, connector configuration, search, and memory records. The
default local workspace in `.env.example` is `MTRNIX`.

## Agent Id

Every MCP request and memory operation is scoped to an **agent identity**. The agent id
tells Metronix **which agent** is calling — memory reads/writes, search calls, and
observability events are all attributed to that id.

You need a stable agent id for two reasons:

1. **Acting on behalf of an agent** — Send the same id in the `X-Agent-Id` header on every
   MCP connection and in the `agent_id` argument of memory tools. Metronix uses it to isolate
   memory per agent and to log tool activity under the correct identity.
2. **Linking to Metronix Console (corporate version)** — In Metronix Console you attach an
   external runtime (Hermes, Cursor, etc.) to a registered agent record. The id you use in MCP
   headers must match that agent's UUID in Console so sessions, memory, and activity appear
   under the right agent.

Use a stable id per runtime — for example `cursor-local`, `claude-desktop-main`, or the UUID
returned by `POST /api/v1/agents` / created in the UI.

MCP clients should send:

```text
X-Agent-Id: <agent-id>
Authorization: Bearer <METRONIX_MCP_API_KEY>
```

Memory tool calls should also pass `agent_id` explicitly in their arguments.
