# Install path audit (from zero to a recalled memory)

Written before the one-command installer work (branch `feat/one-command-install`).
Source: README.md, install.md, docs/deployment.md, connecting_to_agent.md,
docker-compose.yml, Dockerfile, install.sh, scripts/install-bootstrap.sh,
src/metronix/storage/migrations.py, src/metronix/api/{app.py,routes/health.py},
issues #537, #539, #540, #541.

## Current from-zero path (main @ 60555e7)

| # | Step | Who | Notes |
|---|------|-----|-------|
| 1 | `curl -fsSL https://mtrnix.com/install.sh \| bash` or `git clone` + `./install.sh` | user | Bootstrap clones the **latest release tag**, not `main`. |
| 2 | `check_prereqs`: docker, compose, daemon reachable | install.sh | Fails fast with a hint. |
| 3 | `configure`: copy `.env.example` -> `.env`, generate `POSTGRES_PASSWORD`, `NEO4J_PASSWORD`, `METRONIX_MCP_API_KEY`, `FERNET_KEY`, `METRONIX_SECRET_KEY` | install.sh | `AUTH_PASSWORD` is **not** generated. |
| 4 | `docker compose up -d --build` | install.sh | Builds the API (pip, CPU torch) and SPLADE images, pulls postgres, qdrant, neo4j, redis, ollama. |
| 5 | Ollama container pulls `nomic-embed-text`, then `qwen2.5:3b`, inside its entrypoint | compose | Ollama healthcheck only checks the TCP port, so the API starts before the models exist. |
| 6 | API lifespan runs `alembic upgrade head` | app.py | Exceptions are logged as `migrations.failed` and swallowed. |
| 7 | `wait_health`: poll `/health` up to 5 min | install.sh | `/health` is a constant `{"status":"ok"}`. Timeout is a warning, exit code stays 0. |
| 8 | `connect_agent` with `-y` -> `connect_hermes` (or Claude Code / Codex / OpenClaw) | install.sh | Wires the agent with the **shared** `METRONIX_MCP_API_KEY`. |
| 9 | User adds `AUTH_PASSWORD` to `.env`, recreates the API, logs in, creates a `mtk_` key by hand, edits client config | user (README "Example in 5 minutes") | Five manual steps; only path to working memory tools. |

## Failure points

| ID | Where | Failure | Symptom today | Issue |
|----|-------|---------|---------------|-------|
| F1 | step 6 | Migration raises (e.g. `No module named 'psycopg'`, DB auth) | Logged only; `/health` 200, `/ready` 200; most tables missing | #539, #537 (driver fixed; masking not) |
| F2 | step 5/7 | Embedding model not pulled yet / pull failed | `/ready` body says `degraded` but **HTTP 200**; nothing polls `/ready` | #541 (body fixed, status code not) |
| F3 | step 7 | `/ready` never consulted by the installer | Installer prints "Metronix Core is up" while degraded | — |
| F4 | step 7 | API never becomes healthy within 5 min | Warning, exit 0 — silent for scripts/CI | — |
| F5 | step 3/9 | No `AUTH_PASSWORD` -> no admin seeded -> no way to mint a `mtk_` key | `user_store.admin.not_seeded`; README asks user to edit `.env` and recreate | — |
| F6 | step 8 | Agents wired with shared `METRONIX_MCP_API_KEY` | `/mcp` works, every `metronix_memory_*` returns `AUTH_REQUIRED` | #540 |
| F7 | step 8 | `print_links` advertises `admin@metronix.local / metronix` | No such account exists (F5) | — |
| F8 | step 4 | Image pulls + API build ~10 min with plain output under non-TTY | Looks hung in CI / piped runs | — |
| F9 | step 4 | `Dockerfile` copies `src/` before `pip install` | Any source change re-installs all deps (slow rebuilds) | — |
| F10 | step 3 | Credentials scattered: `.env`, README, admin password chosen by hand, key printed once by API | Users mix up the shared key and the personal key | #540 |
| F11 | step 1 | Bootstrap installs the latest **tag** | Fixes on `main` reach curl users only after a release | — |
| F12 | step 3/4 | Existing DB volume with a different password | Already handled by install.sh guards (`assert_recoverable_db_passwords`, `warn_if_db_auth_failed`) | — |

## What the one-command install closes

- F1, F2: `/health` returns 503 when startup migrations failed; `/ready` returns 503
  unless Postgres is at the Alembic head, Qdrant/Neo4j answer and the embedding
  model is installed.
- F3, F4, F8: `scripts/quickstart.sh` waits on `/ready` with per-service progress and
  Ollama pull progress, and exits non-zero on timeout.
- F5, F6, F7, F10: install.sh generates `AUTH_PASSWORD` in the same place as every other
  secret; `scripts/provision_agent.sh` logs in, creates a per-agent `mtk_` key, stores it
  in `.env` and writes Claude Desktop / Cursor / VS Code configs with it.
- End-to-end proof: `scripts/smoke_e2e.sh` stores a fact over MCP with the per-agent key,
  restarts `metronix-core`, and recalls it.
- F9, F11: documented, not changed here.
