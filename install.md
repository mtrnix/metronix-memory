# Installing Metronix Core

This is the complete, by-hand installation guide for the Metronix Core backend. It takes
you from an empty machine to a running stack you can verify with a health check.

Metronix runs as a Docker Compose stack. The canonical Compose file is
**`docker-compose.full.yml`** — use it for every command in this guide.
Once the backend is running, connect an AI agent to it with
[`connecting_to_agent.md`](connecting_to_agent.md).

> **Prefer one command?** From the repo root, `./install.sh` automates steps 3–5 (writes
> `.env`, generates secrets, builds, launches, and health-checks). This page is the by-hand
> reference — use it when you want full control or need the troubleshooting section. Run
> `./install.sh --help` for flags (`--provider`, `--api-key`, `--openwebui`, `--reconfigure`,
> `--yes`).

## Overview

The install is five steps:

1. [Check prerequisites](#1-prerequisites)
2. [Clone the repository](#2-clone-the-repository)
3. [Configure `.env`](#3-configure-env) — pick an LLM provider and set the MCP key
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

You must set two things: an **LLM provider** and the **MCP API key**.

### 3a. LLM provider

When using metronix-memory you need an LLM for query routing and query enrichment.

Pick a provider in `.env`:

- **Ollama (default)** — bundled, no API key: `LLM_PROVIDER=ollama`
- **Custom** — any OpenAI-compatible endpoint (DeepSeek, OpenRouter, vLLM, …):

```ini
LLM_PROVIDER=custom
LLM_PROVIDER_URL=https://your-llm-endpoint/v1
LLM_PROVIDER_API_KEY=your-key
LLM_PROVIDER_MODEL=deepseek-chat   # model the endpoint serves (required)
```

### 3b. MCP API key

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

> The default workspace id is pre-set to `MTRNIX` (`DEFAULT_WORKSPACE_ID` in `.env`). You
> will need this value, and your MCP key, when you connect an agent.

## 4. Launch

Build and start the stack. The first run builds images from source and pulls Ollama models,
which takes about **10–15 minutes**. Subsequent runs are fast.

**Backend only** — PostgreSQL, Qdrant, Neo4j, Redis, Ollama, SPLADE, embedding proxy, and
the Metronix API:

```bash
docker compose -f docker-compose.full.yml up -d --build
```

**Backend + Open WebUI** — adds a browser chat interface at `http://localhost:3080`:

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

Open WebUI requires no login and connects to Metronix automatically via the pre-configured
`OPENAI_API_BASE_URL`.

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
| MCP endpoint | `http://localhost:8000/mcp` |
| OpenAI-compatible API | `http://localhost:8000/v1` |
| Open WebUI (with `--profile openwebui`) | `http://localhost:3080` |

**Next step:** connect an agent over MCP — see
[`connecting_to_agent.md`](connecting_to_agent.md).

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
