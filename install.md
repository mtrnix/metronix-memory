# Metronix Core Install Reference

This file is the detailed installation and troubleshooting reference.

For the short walkthrough, use [`manual.md`](manual.md). For runtime-specific setup, use
the guides under [`docs/integrations/`](docs/integrations/).

## Canonical Compose File

Use:

```bash
docker-compose.full.yml
```

Do not use older compose paths from historical docs or stale examples.

## Prerequisites

- Docker Engine or Docker Desktop
- Docker Compose v2 plugin or legacy `docker-compose`
- About 15 GB of free disk space
- Enough patience for first-run image builds and Ollama pulls

Verify Docker:

```bash
docker --version
docker compose version 2>/dev/null || docker-compose --version
docker info >/dev/null 2>&1 && echo "daemon OK" || echo "START DOCKER DAEMON"
```

## `.env` Setup

Create the file:

```bash
cp .env.example .env
```

Choose one model provider.

### DeepSeek

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-deepseek-key
```

### OpenRouter

```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-your-openrouter-key
```

### Built-in Ollama

```ini
LLM_PROVIDER=ollama
```

### External Ollama

```ini
LLM_PROVIDER=ollama
OLLAMA_HOST=http://your-ollama-host:11434
```

### Custom OpenAI-compatible provider

```ini
LLM_PROVIDER=custom
CUSTOM_LLM_URL=https://your-llm-endpoint/v1
CUSTOM_LLM_API_KEY=your-key
```

### MCP authentication

Generate a token:

```bash
openssl rand -hex 32
```

Add it to `.env`:

```ini
METATRON_MCP_API_KEY=<paste-the-generated-token>
```

Metatron expects:

```text
Authorization: Bearer <METATRON_MCP_API_KEY>
```

for HTTP MCP clients.

## Launch Modes

### Backend only

```bash
docker compose -f docker-compose.full.yml up -d --build
```

### Backend plus Open WebUI

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

First startup may take 10-15 minutes.

## External Ports

These are the exposed host ports from `docker-compose.full.yml`.

| Service | Port |
|---|---|
| API | `8001` |
| PostgreSQL | `5433` |
| Qdrant HTTP | `6335` |
| Qdrant gRPC | `6336` |
| Neo4j HTTP | `7475` |
| Neo4j bolt | `7688` |
| Redis | `6380` |
| Ollama | `11435` |
| SPLADE | `8080` |
| Embedding proxy | `8002` |
| Open WebUI | `3080` |

## Important URLs

| Surface | URL |
|---|---|
| Health | `http://localhost:8001/health` |
| Ready | `http://localhost:8001/ready` |
| REST API | `http://localhost:8001/api/v1` |
| MCP | `http://localhost:8001/mcp` |
| OpenAI-compatible API | `http://localhost:8001/v1` |
| Open WebUI | `http://localhost:3080` |

Inside Docker, Open WebUI talks to Metatron at:

```text
http://metatron-core:8000/v1
```

That is the internal container URL, not the host URL. This distinction causes an
embarrassing number of avoidable setup mistakes.

## Verification

Check container status:

```bash
docker compose -f docker-compose.full.yml ps
```

Check API health:

```bash
curl http://localhost:8001/health
```

Check readiness:

```bash
curl http://localhost:8001/ready
```

## Common Operations

View logs:

```bash
docker compose -f docker-compose.full.yml logs metatron-core
```

Restart the API:

```bash
docker compose -f docker-compose.full.yml restart metatron-core
```

Rebuild after config or code changes:

```bash
docker compose -f docker-compose.full.yml up -d --build --force-recreate
```

Stop:

```bash
docker compose -f docker-compose.full.yml down
```

Stop and remove volumes:

```bash
docker compose -f docker-compose.full.yml down -v
```

## Troubleshooting

### Docker daemon not running

Linux:

```bash
sudo systemctl start docker
```

macOS: launch Docker Desktop, OrbStack, or `colima start`.

### macOS Docker permission weirdness

```bash
sudo chown -R $(whoami):staff ~/.docker
```

### Linux Docker permissions

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Port already in use

```bash
docker compose -f docker-compose.full.yml down
sudo lsof -i :8001
```

### MCP returns `401`

Make sure your client sends:

```text
Authorization: Bearer <METATRON_MCP_API_KEY>
```

and that the token matches `.env`.

### Open WebUI cannot connect

Check API health first:

```bash
curl http://localhost:8001/health
```

Then inspect logs:

```bash
docker compose -f docker-compose.full.yml logs open-webui
```

## Next Step

Use the runtime guide that matches your client:

- [`docs/integrations/hermes-agent.md`](docs/integrations/hermes-agent.md)
- [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md)
- [`docs/integrations/ollama-local-models.md`](docs/integrations/ollama-local-models.md)
- [`docs/integrations/claude-code.md`](docs/integrations/claude-code.md)
- [`docs/integrations/codex.md`](docs/integrations/codex.md)
- [`docs/integrations/opencode.md`](docs/integrations/opencode.md)
- [`docs/integrations/pi.md`](docs/integrations/pi.md)
- [`docs/integrations/langchain.md`](docs/integrations/langchain.md)
- [`docs/integrations/sdk-python.md`](docs/integrations/sdk-python.md)
- [`docs/integrations/sdk-go.md`](docs/integrations/sdk-go.md)
- [`docs/integrations/n8n.md`](docs/integrations/n8n.md)
- [`docs/integrations/nanoclaw.md`](docs/integrations/nanoclaw.md)
- [`docs/integrations/nanobot.md`](docs/integrations/nanobot.md)
- [`docs/integrations/atomic-chat.md`](docs/integrations/atomic-chat.md)
