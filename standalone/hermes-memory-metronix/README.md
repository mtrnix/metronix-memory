# hermes-memory-metronix

Standalone Hermes memory-provider plugin scaffold for Metronix.

This directory is intentionally kept out of Metronix core runtime wiring.
It exists as a standalone plugin repo candidate that can be extracted and
published separately, matching the Hermes maintainer guidance on
`NousResearch/hermes-agent#57100`.

## Status

This is a scaffold, not a finished public plugin release.

What it already does:

- Implements the Hermes `MemoryProvider` contract
- Prefetches relevant Metronix memory records before a turn
- Mirrors Hermes `memory(action="add")` writes into Metronix
- Optionally writes completed turns as session-scoped Metronix memory
- Supports bearer-token auth, with email/password login fallback

What is intentionally still conservative:

- No custom Hermes setup wizard yet
- No extra provider-specific model tools yet
- Prefetch currently targets `/api/v1/memory/search`
- Knowledge-document / page retrieval is left as a follow-up

## Layout

Hermes discovers user-installed memory providers from:

- `~/.hermes/plugins/<name>/__init__.py`

So the installable plugin directory is:

- `plugin/metronix/`

## Local install for Hermes

Copy the plugin directory into your Hermes home:

```bash
mkdir -p ~/.hermes/plugins
cp -R plugin/metronix ~/.hermes/plugins/metronix
```

Then set Hermes to use it:

```yaml
memory:
  provider: metronix
```

Or per-session:

```bash
hermes chat --memory-provider metronix
```

## Plugin config

The plugin reads non-secret config from:

- `$HERMES_HOME/metronix.json`

And secrets from:

- `$HERMES_HOME/.env`
- process environment

Example `metronix.json`:

```json
{
  "base_url": "http://localhost:8000",
  "workspace_id": "MTRNIX",
  "agent_id": "hermes",
  "prefetch": true,
  "prefetch_top_k": 8,
  "prefetch_types": ["fact", "preference", "pinned"],
  "cite_sources": true,
  "write_through": true,
  "write_scope": "workspace",
  "sync_turns": true
}
```

Secrets:

```bash
METRONIX_AUTH_TOKEN=...
# or:
METRONIX_EMAIL=admin@metronix.local
METRONIX_PASSWORD=...
```

Important:

- `METRONIX_AUTH_TOKEN` must be a REST JWT or personal API key for `/api/v1/*`
- `METRONIX_MCP_API_KEY` is for `/mcp`, not `/api/v1/memory/*`
- if you provide both a bearer token and login credentials, the client will
  retry once with a fresh login JWT when the original bearer gets a `401`

## Mapping notes

Hermes write scopes map to Metronix scopes like this:

- `per_agent` -> `per_agent`
- `workspace` -> `global`
- `shared` -> `global`
- `session` -> `session`

The current prefetch path uses Metronix memory search, so `prefetch_types`
maps to Metronix memory kinds:

- `fact`
- `preference`
- `pinned`

`page` is not wired yet because the current scaffold does not call a unified
knowledge-search endpoint.
