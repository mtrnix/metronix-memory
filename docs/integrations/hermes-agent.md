# Hermes Agent

> **MCP authentication mode:** The example targets local `AUTH_ENABLED=false` and uses
> `METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, put a user JWT in the same Bearer
> header; the shared key is ignored.

## Recommended mode

Use Metronix Memory as an HTTP MCP server today.

That is still the recommended production path right now.
It is the best-supported integration for search, memory, and retrieval.

If you want native Hermes memory-provider hooks such as prefetch injection
and write-through from `memory(action="add")`, build that as a standalone
Hermes plugin repo rather than an in-tree Hermes contribution. A scaffold for
that direction lives in:

- `standalone/hermes-memory-metronix/`

## What you need

- Metronix Memory running locally or remotely
- an MCP bearer credential: `METRONIX_MCP_API_KEY` from `.env` when
  `AUTH_ENABLED=false`, or a user JWT when `AUTH_ENABLED=true`
- a stable Hermes agent id
- a workspace id such as `MTRNIX`

## Connection values

```text
URL:          http://localhost:8000/mcp
Authorization: Bearer <MCP_API_KEY_OR_JWT>
X-Agent-Id:    <stable-hermes-agent-id>
```

## Example Hermes config

```yaml
mcp_servers:
  metronix:
    url: http://localhost:8000/mcp
    headers:
      Authorization: "Bearer <MCP_API_KEY_OR_JWT>"
      X-Agent-Id: "<AGENT_UUID>"
    timeout: 180
    connect_timeout: 60
```

Restart Hermes after changing MCP configuration.

## Automated setup

`./install.sh --connect-hermes -y` can add the MCP server and an availability
note to `SOUL.md` when it finds an existing Hermes configuration. If the
installer cannot safely edit that configuration, it writes deployment-specific prompts to
`metronix-hermes-setup/` instead. Those generated files contain the MCP key and
are intentionally ignored by Git.

Making Metronix the primary durable-memory source and migrating existing
memories remain deliberate follow-up steps. The prompt-driven path needs the
Hermes `file`, `terminal`, and `code_execution` toolsets; the canonical prompt
templates live in [`hermes/`](hermes/).

## Verify

Call:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_list(workspace_id="MTRNIX", agent_id="<AGENT_UUID>", limit=5)
```

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`). With `AUTH_ENABLED=false`, check that `METRONIX_MCP_API_KEY` in `.env` matches the Hermes config. With `AUTH_ENABLED=true`, use a valid user JWT instead.

**Tools not appearing after registration:** Restart Hermes after changing MCP configuration — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer` header matches the configured MCP mode: a user JWT for `AUTH_ENABLED=true`, or `METRONIX_MCP_API_KEY` for `AUTH_ENABLED=false`.

## Native provider credentials

The standalone native provider calls `/api/v1/*`, so configure a separate,
revocable REST key on the Hermes host:

```bash
# Written to the Hermes host's secret environment, never to Metronix .env.
METRONIX_AUTH_TOKEN=mtk_<one-time-value-from-the-admin-API>
```

Create a labelled key for the actual user or service identity that should own
the provider. The provider receives that identity's live role and workspace
access. The local-mode `METRONIX_MCP_API_KEY` only authorizes `/mcp`; using it
as `METRONIX_AUTH_TOKEN` returns `401` on `/api/v1/*`. A hosted MCP JWT is
also not a replacement for a revocable native-provider key.

Rotate a native-provider key by creating a replacement key, updating the
Hermes secret environment, restarting Hermes, validating `/api/v1/auth/me`
through the provider, then revoking the old prefix. Email/password login
remains a fallback for development and JWT refresh; production native
deployments should prefer the revocable API key.

## Recommendation

If you already use Hermes-native memory providers, keep them separate mentally.
Metronix Memory is the durable shared memory and knowledge backend. Treat it like the source of
truth you can inspect, not an invisible sidecar.
