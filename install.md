# Metronix Core Deployment Reference

Use [`manual.md`](manual.md) for the short step-by-step install sequence. This file is the
detailed reference for deployment options, environment variables, ports, verification, and
troubleshooting.

## Canonical Compose File

The canonical Docker Compose file is:

```bash
docker-compose.full.yml
```

Do not use any other Compose file found in the repository.

## Prerequisites

- Docker Engine or Docker Desktop.
- Docker Compose v2 plugin, or legacy `docker-compose`.
- Python 3.12+ for local development and tests.
- Around 15 GB of free disk space for images, volumes, build cache, and first-run Ollama
  model downloads.

Verify Docker:

```bash
docker --version
docker compose version 2>/dev/null || docker-compose --version
docker info >/dev/null 2>&1 && echo "daemon OK" || echo "START DOCKER DAEMON"
```

## Environment

Create `.env`:

```bash
cp .env.example .env
```

Set one LLM provider.

DeepSeek:

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-deepseek-key
```

OpenRouter:

```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-your-openrouter-key
```

Built-in Ollama from Compose:

```ini
LLM_PROVIDER=ollama
```

External Ollama:

```ini
LLM_PROVIDER=ollama
OLLAMA_HOST=http://your-ollama-host:11434
```

Custom OpenAI-compatible provider:

```ini
LLM_PROVIDER=custom
CUSTOM_LLM_URL=https://your-llm-endpoint/v1
CUSTOM_LLM_API_KEY=your-key
```

Generate and set an MCP API key:

```bash
openssl rand -hex 32
```

```ini
METRONIX_MCP_API_KEY=<paste-the-generated-token>
```

External agents use this token when connecting to `/mcp`.

## Launch Profiles

Backend stack:

```bash
docker compose -f docker-compose.full.yml up -d --build
```

Backend + Open WebUI:

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

First startup can take 10-15 minutes while images build and local models download.

## Ports

| Service | Port |
|---|---|
| API | `8000` |
| PostgreSQL | `5433` |
| Qdrant | `6335` |
| Qdrant gRPC | `6336` |
| Neo4j HTTP | `7475` |
| Neo4j bolt | `7688` |
| Redis | `6380` |
| SPLADE | `8080` |
| Embedding proxy | `8002` |
| Ollama | `11435` |
| Open WebUI | `3080` |

## Verify

```bash
docker compose -f docker-compose.full.yml ps
curl http://localhost:8000/health
```

Open WebUI, when enabled:

```text
http://localhost:3080
```

MCP endpoint:

```text
http://localhost:8000/mcp
```

OpenAI-compatible API:

```text
http://localhost:8000/v1
```

## Common Operations

View logs:

```bash
docker compose -f docker-compose.full.yml logs metronix-core
```

Restart the API:

```bash
docker compose -f docker-compose.full.yml restart metronix-core
```

Rebuild after `.env` or source changes:

```bash
docker compose -f docker-compose.full.yml up -d --build --force-recreate
```

Stop the stack:

```bash
docker compose -f docker-compose.full.yml down
```

Stop and remove volumes:

```bash
docker compose -f docker-compose.full.yml down -v
```

## Troubleshooting

### Docker daemon is not running

Linux:

```bash
sudo systemctl start docker
```

macOS or Windows: start Docker Desktop. On macOS you can also use OrbStack or Colima.

### Docker permission denied on Linux

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Or prefix Docker commands with `sudo`.

### Docker build permission denied on macOS

Docker Desktop can lose ownership of `~/.docker` after an update:

```bash
sudo chown -R $(whoami):staff ~/.docker
```

### Port already in use

Stop any previous Metronix run:

```bash
docker compose -f docker-compose.full.yml down
```

Check the occupied port:

```bash
sudo lsof -i :8000
```

On Windows PowerShell:

```powershell
netstat -ano | findstr :8000
```

### MCP returns 401

Check that the agent configuration uses:

```text
Authorization: Bearer <METRONIX_MCP_API_KEY>
```

The token must match the value in the server `.env`.

### Open WebUI cannot reach Metronix

Verify the API health endpoint first:

```bash
curl http://localhost:8000/health
```

Then inspect Open WebUI logs:

```bash
docker compose -f docker-compose.full.yml logs open-webui
```

## Agent Setup

For MCP agent setup, use [`connecting_to_agent.md`](connecting_to_agent.md). Runtime-specific
guides live under [`docs/integrations/`](docs/integrations/).
