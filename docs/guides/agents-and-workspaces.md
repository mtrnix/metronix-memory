# Agents And Workspaces

> **MCP authentication mode:** Local `AUTH_ENABLED=false` clients may use
> `METRONIX_MCP_API_KEY`. Hosted `AUTH_ENABLED=true` clients must use a user JWT in the
> Bearer header; the shared key is ignored.

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

**Format.** An agent id must be **1–64 characters** from `A–Z a–z 0–9 . _ -`. UUIDs (with or
without dashes) and slugs like `my-agent-001` are fine; spaces, `/`, and other characters are
rejected because the id is used directly in REST paths (`/agents/{id}`). The same rule is
enforced on the `X-Agent-Id` header, the `agent_id` memory-tool argument, and the `id` field
of `POST /api/v1/agents`, so an id an agent self-assigns over MCP can later be registered
verbatim and keep its memory and activity.

MCP clients should send:

```text
X-Agent-Id: <agent-id>
Authorization: Bearer <METRONIX_MCP_API_KEY>
```

Memory tool calls should also pass `agent_id` explicitly in their arguments.
