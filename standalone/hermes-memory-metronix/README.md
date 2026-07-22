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
- Prefetches relevant Metronix memory records before a turn (via a
  background `queue_prefetch()` cache, populated after each turn and read
  synchronously by `prefetch()` — matches Hermes's "prefetch must be fast"
  contract instead of blocking each turn on a live search)
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
# Written to the Hermes host's secret environment, never to Metronix .env.
METRONIX_AUTH_TOKEN=mtk_<one-time-value-from-the-admin-API>
```

Important:

- Create a labelled key for the actual user or service identity that should own
  the provider; it receives that identity's live role and workspace access.
- `METRONIX_AUTH_TOKEN` holds the revocable REST API key for `/api/v1/*`.
  `METRONIX_MCP_API_KEY` only authorizes `/mcp`; using it as
  `METRONIX_AUTH_TOKEN` returns `401` on `/api/v1/*`.
- Rotate by creating a replacement key, updating the Hermes secret environment,
  restarting Hermes, validating `/api/v1/auth/me` through the provider, then
  revoking the old prefix.
- Email/password login remains a fallback for development and JWT refresh;
  production native deployments should prefer the revocable API key.
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

## Migrating an existing llm-wiki into Metronix

Hermes's bundled `llm-wiki` skill maintains a directory of markdown pages
(`entities/`, `concepts/`, `comparisons/`, `queries/`, `raw/`) at `$WIKI_PATH`
(default `~/wiki`). To bulk-ingest an existing wiki into Metronix's Knowledge
Base (chunked, embedded, searchable via `metronix_search_fast`/`metronix_get`):

```bash
python scripts/migrate_wiki.py \
  --wiki-path ~/wiki \
  --base-url http://localhost:8000 \
  --workspace-id MTRNIX \
  --auth-token "$METRONIX_AUTH_TOKEN"
```

Each page becomes a document with `source_type="hermes_llm_wiki"` and a
deterministic `doc_label` derived from its wiki-relative path, so re-running
the script updates existing documents instead of duplicating them. By
default, only `raw/`, `entities/`, `concepts/`, `comparisons/`, and
`queries/` are ingested — `SCHEMA.md`, `index.md`, `log*.md`, and
`_archive/**` are skipped (pass `--include-archive` to include archived
pages instead).

Requires the REST API key in `METRONIX_AUTH_TOKEN` for `/api/v1/*` — not
`METRONIX_MCP_API_KEY`, which only authorizes `/mcp`.
