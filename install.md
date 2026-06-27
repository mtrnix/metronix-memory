# Installing Metronix Core

This is the complete, by-hand installation guide for the Metronix Core backend. It takes
you from an empty machine to a running stack you can verify with a health check.

Metronix runs as a Docker Compose stack. The canonical Compose file is
**`docker-compose.full.yml`** — use it for every command in this guide.
Once the backend is running, connect an AI agent to it with
[`connecting_to_agent.md`](connecting_to_agent.md).

**Quick install** — after you have cloned the repo, `./install.sh` checks Docker, writes
`.env`, builds and starts the stack, health-checks the API, and optionally wires Hermes.

Common flags (see `./install.sh --help` for the full list):

| Flag | Purpose |
|---|---|
| `-y`, `--yes` | Non-interactive; use defaults and flags, never prompt |
| `--mode memory\|answers` | **memory** (default): agent memory over MCP, no chat model. **answers**: Metronix generates replies |
| `--chat-url`, `--chat-model`, `--chat-api-key` | Chat LLM endpoint when `--mode answers` |
| `--openwebui` | Enable Open WebUI (`:3080`); only applies in **answers** mode |
| `--wire-hermes` | Connect Hermes after install (or `./install.sh --wire-hermes -y` alone) |
| `--agent-id`, `--metronix-url` | Override agent id / MCP URL written into Hermes config |
| `--reconfigure` | Re-run `.env` setup even if `.env` already exists |
| `--fresh-docker-reset` | Delete Metronix containers, images, volumes, and build cache before reinstall |

```bash
./install.sh                              # memory store (default)
./install.sh --mode answers \
  --chat-url https://api.deepseek.com/v1 --chat-model deepseek-chat \
  --chat-api-key sk-... --openwebui -y    # answers + Open WebUI, non-interactive
```

*This page is the by-hand reference — use it for full control or troubleshooting.*

## Overview

The install is five steps:

1. [Check prerequisites](#1-prerequisites)
2. [Clone the repository](#2-clone-the-repository)
3. [Configure `.env`](#3-configure-env) — set the MCP key (+ optional chat LLM if using Open WebUI)
4. [Launch the stack](#4-launch)
5. [Verify](#5-verify)

After that, see [Ports](#ports), [Common operations](#common-operations), and
[Troubleshooting](#troubleshooting) for day-to-day reference.

## 1. Prerequisites

- **Docker Engine** or **Docker Desktop**, with the daemon running.
- **Docker Compose v2** (`docker compose`) or the legacy `docker-compose` binary.
- **~15 GB free disk space** — images, build cache, volumes, and first-run Ollama model
  downloads.
- **Python 3.12+** — only if you intend to run tests or develop locally; not required to
  run the stack.

Verify Docker is installed and the daemon is up:

```bash
docker --version
docker compose version 2>/dev/null || docker-compose --version
docker info >/dev/null 2>&1 && echo "Docker is running successfully" || echo "DOCKER DAEMON IS NOT RUNNING! Start Docker via command: 'sudo systemctl start docker' or check prerequisites in install.md for more info"
```

If Docker is missing, install it first:

- Linux: <https://docs.docker.com/engine/install/>
- macOS: <https://docs.docker.com/desktop/setup/install/mac-install/>
- Windows: <https://docs.docker.com/desktop/setup/install/windows-install/>

If the daemon is not running, start it: `sudo systemctl start docker` (Linux), or launch
Docker Desktop / OrbStack / `colima start` (macOS).

> **macOS note.** Docker Desktop can lose ownership of `~/.docker` after an update, which
> makes `docker compose build` fail with `permission denied`. Fix it before step 4:
>
> ```bash
> sudo chown -R $(whoami):staff ~/.docker
> ```

## 2. Clone the repository

```bash
git clone -b develop https://github.com/mtrnix/metronix-memory.git
cd metronix-memory
```

## 3. Configure `.env`

Create your environment file from the template:

```bash
cp .env.example .env
```

For the usual path — **agent memory over MCP** (Hermes, Cursor, Claude Desktop, …) — you
only need to set **`METRONIX_MCP_API_KEY`**. Embeddings for ingest run on the bundled Ollama
container automatically (see [§3d](#3d-bundled-ollama-embeddings)); you do **not** need a chat
LLM in `.env`.

| Scenario | What to set in `.env` |
|---|---|
| **Agent memory (MCP)** — default | `METRONIX_MCP_API_KEY` only |
| **Open WebUI** ([§4](#4-launch)) | MCP key **+** chat LLM ([§3b](#3b-optional-chat-llm-open-webui-or-answer-generation)) |
| **Metronix generates answers** | Same as Open WebUI — custom chat endpoint |

> **`./install.sh`** copies `.env.example` and auto-generates `POSTGRES_PASSWORD`,
> `NEO4J_PASSWORD`, `METRONIX_MCP_API_KEY`, `FERNET_KEY`, and `METRONIX_SECRET_KEY`. On a
> manual install the DB passwords ship blank in `.env.example`; Docker Compose falls back to
> `metronix_dev` for both Postgres and Neo4j unless you set them. Remove any empty
> `NEO4J_AUTH=` line from `.env` — it breaks Neo4j startup (see
> [Troubleshooting](#neo4j-container-is-unhealthy)).

### 3a. MCP API key (required)

The MCP API key guards the MCP server endpoint (`/mcp`), which is how AI agents
(Hermes, Cursor, Claude Desktop, and other MCP clients) connect to Metronix. The key is a
token **you choose** — treat it like a password. You can generate a strong string using:

```bash
openssl rand -hex 32
```

Set it in `.env`:

```ini
METRONIX_MCP_API_KEY=<paste-the-generated-token>
```

Agents send this token as `Authorization: Bearer <token>` when connecting to
`http://localhost:8000/mcp`. The endpoint returns `401` without it.

**MCP URL:** `http://localhost:8000/mcp` is the default value for your host. It maps to the
**`metronix-full-api`** container (`metronix-core` in `docker-compose.full.yml`), port **8000**,
path **`/mcp`**.

> The default workspace id is pre-set to `MTRNIX` (`DEFAULT_WORKSPACE_ID` in `.env`). You
> will need this value, your MCP key, and an agent UUID (configured in the agent runtime, not
> in this `.env`) when you connect an agent — see [`connecting_to_agent.md`](connecting_to_agent.md).

### 3b. Optional: chat LLM (Open WebUI or answer generation)

Configure this **only** if you will run **Open WebUI** ([§4](#4-launch)) or want Metronix
itself to generate chat answers. For agent memory over MCP, **skip this section** — your
external agent handles replies.

Set any OpenAI-compatible chat endpoint in `.env`:

```ini
LLM_PROVIDER=custom
LLM_PROVIDER_URL=https://your-llm-endpoint/v1
LLM_PROVIDER_API_KEY=your-key
LLM_PROVIDER_MODEL=deepseek-chat   # model the endpoint serves (required)
```

With `./install.sh`, use `--mode answers` plus `--chat-url`, `--chat-model`, and optionally
`--chat-api-key` instead of editing by hand.

### 3c. Neo4j authentication

Neo4j requires a username/password. On a **manual** install with unchanged `.env.example`,
the defaults are:

- Username: `neo4j`
- Password: `metronix_dev`

If you change `NEO4J_PASSWORD` in `.env`, use **plain text** only (not hashes). Neo4j does
not accept pre-hashed passwords. The `install.sh` script generates a random password
automatically; if you edit `.env` manually, ensure `NEO4J_PASSWORD` is set to a plain-text
value and leave `NEO4J_AUTH` unset (or do not edit it).

### 3d. Bundled Ollama (embeddings)

Docker Compose starts an **Ollama** container (`metronix-full-ollama`, host port **11435**)
with the rest of the stack — no extra `.env` setup. On first launch its entrypoint runs
**`ollama pull nomic-embed-text`**. That embedding model is required for **data ingest**
(indexing documents, memory records, and connector content into Qdrant).

This is **not** a chat LLM and is separate from [§3b](#3b-optional-chat-llm-open-webui-or-answer-generation).
By default no chat model is downloaded (`OLLAMA_CHAT_MODEL` empty). The first
`docker compose up` may take extra time while the embedding model downloads.

Inside the Docker network the service is `ollama:11434`. Metronix uses it for vector
embeddings only; `./install.sh` in memory mode prints the same: embeddings on bundled
Ollama (`nomic-embed-text`), set up automatically.

## 4. Launch

Build and start the stack. The first run builds images from source and pulls the Ollama
**embedding** model (`nomic-embed-text`), which takes about **10–15 minutes**. Subsequent
runs are fast.

**Backend only** — PostgreSQL, Qdrant, Neo4j, Redis, Ollama (embeddings), SPLADE, embedding
proxy, and the Metronix API:

```bash
docker compose -f docker-compose.full.yml up -d --build
```

**Backend + Open WebUI** — adds a browser chat interface at `http://localhost:3080`.
Configure a chat LLM first ([§3b](#3b-optional-chat-llm-open-webui-or-answer-generation));
Open WebUI calls Metronix's OpenAI-compatible API for answers and is useless without one.

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

Open WebUI requires no login and connects to Metronix automatically via the pre-configured
`OPENAI_API_BASE_URL`.

> **`./install.sh`** enables Open WebUI only in **`--mode answers`**. In memory mode,
> `--openwebui` is ignored with a warning.

## 5. Verify

Check that every service is up and the API is healthy:

```bash
docker compose -f docker-compose.full.yml ps
curl http://localhost:8000/health
```

A healthy backend exposes:

| Surface | URL |
|---|---|
| API health | `http://localhost:8000/health` |
| REST API | `http://localhost:8000/api/v1/*` |
| MCP endpoint | `http://localhost:8000/mcp` — **`metronix-full-api`** container, path `/mcp` (from Docker network: `http://metronix-core:8000/mcp`) |
| OpenAI-compatible API | `http://localhost:8000/v1` |
| Open WebUI (with `--profile openwebui`) | `http://localhost:3080` |

**Next step:** connect an agent over MCP — see
[`connecting_to_agent.md`](connecting_to_agent.md).

**Optional:** run the LongMemEval-S agent-memory benchmark — see
[`docs/benchmarks/longmemeval.md`](docs/benchmarks/longmemeval.md). Configure the benchmark in
`benchmarks/longmemeval/.env.benchmark` (not the repo-root `.env`).

## Using `./install.sh` beyond the first run

If `.env` or containers already exist, re-running `./install.sh` **inspects** the deployment
and offers a menu instead of blindly overwriting config:

| Action | When |
|---|---|
| Fix `.env` and restart | Blank secrets or empty `NEO4J_AUTH=` |
| Rebuild stack | Containers exist but API is down |
| Reset volumes (`down -v`) | Unhealthy Neo4j, or a Postgres/Neo4j password mismatch on an old volume |
| Fresh Docker reset | `--fresh-docker-reset` — removes images, volumes, build cache |
| Reconfigure | `--reconfigure` — rewrite `.env` from scratch |

After a successful install the script may **wire Hermes**:

- Interactive prompt: edit `~/.hermes/config.yaml` + `SOUL.md`, or write a paste-ready guide.
- `./install.sh --wire-hermes -y` — apply MCP wiring without prompting (requires existing `.env`).
- Either way, filled prompts land in **`metronix-hermes-setup/`** (`1-install-mcp.md`,
  `2-memory-source.md`, `3-migrate.md`; gitignored). Paste prompts 2 and 3 after restarting
  Hermes — see [`docs/integrations/hermes.md`](docs/integrations/hermes.md).

Manual install: use [`connecting_to_agent.md`](connecting_to_agent.md) instead of the script
for agent setup.

## Ports

| Service | Host port |
|---|---|
| API | `8000` |
| PostgreSQL | `5433` |
| Qdrant HTTP | `6335` |
| Qdrant gRPC | `6336` |
| Neo4j HTTP | `7475` |
| Neo4j bolt | `7688` |
| Redis | `6380` |
| SPLADE | `8080` |
| Embedding proxy | `8002` |
| Ollama | `11435` |
| Open WebUI | `3080` |

## Common operations

View API logs:

```bash
docker compose -f docker-compose.full.yml logs metronix-core
```

Restart the API:

```bash
docker compose -f docker-compose.full.yml restart metronix-core
```

Rebuild after editing `.env` or source:

```bash
docker compose -f docker-compose.full.yml up -d --build --force-recreate
```

Stop the stack:

```bash
docker compose -f docker-compose.full.yml down
```

Stop the stack and delete all data volumes:

```bash
docker compose -f docker-compose.full.yml down -v
```

## Troubleshooting

### Docker daemon is not running

- Linux: `sudo systemctl start docker`
- macOS / Windows: start Docker Desktop. On macOS, OrbStack or `colima start` also work.

### Permission denied on Linux

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Or prefix Docker commands with `sudo`.

### Build permission denied on macOS

Docker Desktop can lose ownership of `~/.docker` after an update:

```bash
sudo chown -R $(whoami):staff ~/.docker
```

### Port already in use

Stop any previous Metronix run, then find what occupies the port:

```bash
docker compose -f docker-compose.full.yml down
sudo lsof -i :8000                  # Linux / macOS
```

On Windows PowerShell:

```powershell
netstat -ano | findstr :8000
```

### MCP endpoint returns 401

The agent must send the configured key:

```text
Authorization: Bearer <METRONIX_MCP_API_KEY>
```

The token must exactly match `METRONIX_MCP_API_KEY` in the server `.env`.

### Open WebUI cannot reach Metronix

Confirm the API is healthy first, then inspect Open WebUI logs:

```bash
curl http://localhost:8000/health
docker compose -f docker-compose.full.yml logs open-webui
```

### Neo4j container is unhealthy

If Neo4j fails to start with the error `dependency failed to start: container
metronix-full-neo4j is unhealthy`, check the logs:

```bash
docker logs metronix-full-neo4j
```

A common cause is an invalid `NEO4J_AUTH` value in `.env`. If `NEO4J_AUTH` is set to an
empty string, Neo4j receives a blank username and rejects it. Fix:

```bash
# Remove the NEO4J_AUTH= line from .env
sed -i '/^NEO4J_AUTH=$/d' .env

# Restart the stack
docker compose -f docker-compose.full.yml down
docker compose -f docker-compose.full.yml up -d
```

Also ensure `NEO4J_PASSWORD` is a **plain text** password, not a hash. Neo4j does not accept
pre-hashed passwords.

### Neo4j password changed on an existing volume

Neo4j only sets the initial password on **first startup**. If you change `NEO4J_PASSWORD`
in `.env` on a system that already has the Neo4j data volume, the database keeps the old
password and the healthcheck (which reads the new one) will fail.

To reset the database with the new password:

```bash
docker compose -f docker-compose.full.yml down -v
docker compose -f docker-compose.full.yml up -d
```

> **Warning:** `down -v` deletes ALL data volumes (PostgreSQL, Qdrant, Neo4j, Redis,
> Ollama). This is a full reset — only do it if you're starting fresh.

### Postgres rejects the password ("password authentication failed")

Like Neo4j, Postgres fixes its password on **first startup** and keeps it in its data
volume. If `POSTGRES_PASSWORD` in `.env` later differs from that value, Postgres still
starts (its healthcheck does not authenticate) but rejects every query with
`password authentication failed for user "metronix"` — so the stack can look healthy while
memory writes fail. This usually happens when `.env` is deleted or regenerated **without**
also resetting the volume.

```bash
docker logs metronix-full-postgres | grep "password authentication failed"
```

Restore the original `POSTGRES_PASSWORD` in `.env`, or reset the data (full wipe):

```bash
docker compose -f docker-compose.full.yml down -v
docker compose -f docker-compose.full.yml up -d --build
```

> **Warning:** `down -v` deletes ALL data volumes. Only do this when starting fresh.
