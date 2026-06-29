# Inspecting the Postgres Database (Docker)

The Metronix Core stack runs Postgres in the `metronix-full-postgres` container.

| Setting | Value |
|---|---|
| Container | `metronix-full-postgres` |
| Image | `postgres:16-alpine` |
| Host port | `5433` → container `5432` |
| User | `metronix` |
| Database | `metronix` |

> Credentials are read from `.env` (`POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD`).
> The commands below run `psql` *inside* the container, so no password is needed.

## Connecting

```bash
# Open an interactive psql shell inside the container
docker exec -it metronix-full-postgres psql -U metronix -d metronix

# Connect from the host (port 5433) — will prompt for the password from .env
psql "postgresql://metronix@localhost:5433/metronix"
```

## Inspecting structure

```bash
# List all tables
docker exec metronix-full-postgres psql -U metronix -d metronix -c "\dt"

# Describe a single table
docker exec metronix-full-postgres psql -U metronix -d metronix -c "\d raw_documents"

# Approximate row counts for every table (cheap, uses stats)
docker exec metronix-full-postgres psql -U metronix -d metronix -c "
SELECT relname AS table, n_live_tup AS approx_rows
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC, relname;"
```

## Reading data

```bash
# Users
docker exec metronix-full-postgres psql -U metronix -d metronix \
  -c "SELECT id, username, email, role, is_active, created_at FROM users;"

# Stored documents (expanded output -x is handy for wide rows)
docker exec metronix-full-postgres psql -U metronix -d metronix -x \
  -c "SELECT id, workspace_id, connector_type, source_id, title, status FROM raw_documents;"

# Agent activity log
docker exec metronix-full-postgres psql -U metronix -d metronix -x \
  -c "SELECT id, workspace_id, agent_id, event_type, created_at FROM agent_activity_log ORDER BY id;"
```

## Rendering a table as Markdown

`psql` has no native markdown format (only `aligned`, `csv`, `asciidoc`, `html`, …),
so build the markdown table in SQL with `-t -A` (tuples-only, unaligned):

```bash
docker exec metronix-full-postgres psql -U metronix -d metronix -t -A -c "
WITH cols AS (
  SELECT
    left(id, 12)              AS id,
    workspace_id,
    connector_type,
    source_id,
    title,
    status,
    qdrant_synced::text,
    graph_synced::text,
    to_char(created_at, 'YYYY-MM-DD HH24:MI') AS created_at
  FROM raw_documents
  ORDER BY created_at
)
SELECT '| id | workspace | connector | source_id | title | status | qdrant | graph | created |'
UNION ALL
SELECT '|---|---|---|---|---|---|---|---|---|'
UNION ALL
SELECT '| ' || concat_ws(' | ', id, workspace_id, connector_type, source_id, title, status, qdrant_synced, graph_synced, created_at) || ' |'
FROM cols;"
```

Save straight to a `.md` file by appending `> raw_documents.md` to the command.

Current output:

| id | workspace | connector | source_id | title | status | qdrant | graph | created |
|---|---|---|---|---|---|---|---|---|
| 6c76ec098b0e | MTRNIX | memory | product-open-core-boundaries | product/open-core-boundaries.md | active | true | true | 2026-06-25 15:12 |
| 9bd6ececd5d0 | MTRNIX | memory | product-legacy | product/legacy.md | active | true | true | 2026-06-25 15:12 |

## Tips

- Add `-x` for expanded (record-per-row) output on wide tables.
- Add `-A -F','` to get CSV-style output for piping/export.
- Pipe a `.sql` file in: `docker exec -i metronix-full-postgres psql -U metronix -d metronix < query.sql`
- Dump the whole DB: `docker exec metronix-full-postgres pg_dump -U metronix -d metronix > backup.sql`
