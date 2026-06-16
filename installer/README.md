# Metatron Core Installer

One-command installer for Metatron Core — hybrid RAG + agent memory infrastructure.

## Quick Start

```bash
git clone -b feature/installer-cross-platform https://github.com/mtrnix/metatroncore.git
cd metatroncore
./install/bootstrap.sh
```

The wizard will guide you through deployment mode, LLM provider, and profile selection.
After completion, UI endpoints are printed with direct links.

**Prerequisites:** Docker (daemon running), `curl` (for uv bootstrap), bash.

## Profiles

| Profile | Services | UI Ports |
|---------|----------|----------|
| **minimal** | core (postgres, qdrant, neo4j, redis, splade, API, freshness) + metatron-ui | `:3000` |
| **full** | core + ollama + embedding-proxy + all UIs | `:3000` `:3001` `:3080` |
| **custom** | core + pick from: ollama, embedding-proxy, openwebui, ui, ui-cc | depends on selection |

Core = always-on services: postgres, qdrant, neo4j, redis, splade, metatron-core, freshness-worker.

## Options

```bash
./install/bootstrap.sh --dry-run          # generate .env, print it, don't touch Docker
./install/bootstrap.sh --non-interactive  # server + minimal + deepseek, no questions
./install/bootstrap.sh --config answers.yaml  # all answers from a YAML file
```

### answers.yaml example

```yaml
mode: server
profile: full
llm_provider: deepseek
llm_api_key: sk-your-key
integrations:
  openai_compat_key: my-key
```

## Existing Install

If a previous `.env` or running containers are detected, you'll be asked:

- **reconfigure** — run wizard, rewrite `.env`, pull & start
- **restart** — restart containers, no pull, keep config
- **upgrade** — pull new images, keep current `.env`
- **uninstall** — stop & remove containers

## Post-Install

```bash
# Status
docker compose -f install/docker-compose.yml ps

# Logs
docker compose -f install/docker-compose.yml logs -f

# Stop
docker compose -f install/docker-compose.yml down

# Stop + remove all data
docker compose -f install/docker-compose.yml down --volumes
```

## LLM Providers

| Provider | Requires |
|----------|----------|
| `ollama` | bundled (full) or external host URL (minimal) |
| `deepseek` | API key |
| `openrouter` | API key |
| `custom` | API key + endpoint URL |

## Service Ports

| Service | Port |
|---------|------|
| Metatron API | 8000 |
| Metatron UI | 3000 |
| Metatron UI CC | 3001 |
| Open WebUI | 3080 |
| Ollama | 11435 |
| PostgreSQL | 5433 |
| Qdrant HTTP | 6335 |
| Neo4j Bolt | 7688 |
| Redis | 6379 |
| SPLADE | 8080 |
| Embedding Proxy | 8001 |
