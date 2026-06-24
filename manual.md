# Metronix Core — Manual Install (backend only, optional Open WebUI)

> For the automated install, run `./install.sh` from the repo root. This file documents the manual steps.

## 1. Clone the repository

```bash
git clone -b develop https://github.com/mtrnix/metronixcore.git
cd metronixcore
```

## 2. Verify Docker and Docker Compose

```bash
docker --version
docker compose version 2>/dev/null || docker-compose --version
docker info >/dev/null 2>&1 && echo "daemon OK" || echo "DOCKER DAEMON IS NOT STARTED. START DOCKER DAEMON USING sudo systemctl start docker"
```

### macOS — check buildx cache permissions

Docker Desktop can lose ownership of `~/.docker` after an update, causing
`permission denied` on `docker compose build`. Check and fix **before** step 4:

```bash
ls -ld ~/.docker/buildx 2>/dev/null || echo "OK (no buildx yet)"
# If you got "permission denied" above:
sudo chown -R $(whoami):staff ~/.docker
```

If Docker is missing:
- **Linux:** https://docs.docker.com/engine/install/
- **macOS:** https://docs.docker.com/desktop/setup/install/mac-install/
- **Windows:** https://docs.docker.com/desktop/setup/install/windows-install/

Daemon not responding: `sudo systemctl start docker` (Linux) or launch Docker Desktop /
OrbStack / `colima start` (macOS).

Free disk space: about 15 GB (images + build + volumes + Ollama models on first run).

## 3. Prepare .env

```bash
cp .env.example .env
```

Open `.env` and set:

### 3a. LLM provider + API key

Pick one provider, set `LLM_PROVIDER` and the corresponding key.

deepseek:
```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-deepseek-key
```

openrouter:
```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-your-openrouter-key
```

ollama (external host):
```ini
LLM_PROVIDER=ollama
OLLAMA_HOST=http://your-ollama-host:11434
```

ollama (built-in, works out of the box with docker-compose.full.yml):
```ini
LLM_PROVIDER=ollama
```

custom:
```ini
LLM_PROVIDER=custom
CUSTOM_LLM_URL=https://your-llm-endpoint/v1
CUSTOM_LLM_API_KEY=your-key
```

### 3b. MCP auth

Controls access to the MCP server endpoint (`/mcp`). MCP is the primary integration
path for AI agents (Hermes, Cursor, Claude Desktop). The key is a token **you create**
— any string, like a password. Generate a strong one:

```bash
openssl rand -hex 32
```

Set it in `.env`:

```ini
METRONIX_MCP_API_KEY=<paste-the-generated-token>
```

External agents use this token to authenticate when connecting to
`http://localhost:8000/mcp`. Without it, MCP connections are rejected.

## 4. Launch

### Option A — backend only (postgres, qdrant, neo4j, redis, ollama, splade, metronix-core)

```bash
docker compose -f docker-compose.full.yml up -d --build
```

### Option B — backend + Open WebUI (chat interface at :3080)

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

Open `http://localhost:3080` — no login required. Open WebUI connects to Metronix
automatically via the pre-configured `OPENAI_API_BASE_URL`.

First run builds images from source and pulls Ollama models (about 10-15 minutes).

Verify:
```bash
docker compose -f docker-compose.full.yml ps
curl http://localhost:8000/health
```

Ports: API `:8000` | PostgreSQL `:5433` | Qdrant `:6335` | Neo4j bolt `:7688` |
Redis `:6380` | Ollama `:11435` | SPLADE `:8080` | Open WebUI `:3080` (option B)

For a detailed deployment reference, other profiles, and troubleshooting, see
[`install.md`](install.md).

## 5. Troubleshooting

### Docker on macOS — permission denied

See step 2 — `~/.docker` ownership check. Fix: `sudo chown -R $(whoami):staff ~/.docker`.

### Permission denied (Linux)

If `docker compose` fails with «permission denied»:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Or prefix commands with `sudo docker compose ...`.

### Daemon not responding

```bash
# Linux
sudo systemctl start docker

# macOS — launch Docker Desktop / OrbStack, or
colima start
```

### Port already in use

```bash
docker compose -f docker-compose.full.yml down   # clean up previous run
sudo lsof -i :8000                                # check what occupies the port
```

### Rebuild after .env changes

```bash
docker compose -f docker-compose.full.yml up -d --build --force-recreate
```
