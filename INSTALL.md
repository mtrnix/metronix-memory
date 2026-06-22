# Metronix Core — Installation Guide

One command to install Metronix Core: hybrid RAG + agent memory infrastructure.

---

## Prerequisites

### GitHub access (required — private repository)

The `mtrnix/metatroncore` repository is private. You need a GitHub account that has been granted access, plus authentication configured for `git clone`.

**Option A — HTTPS with personal access token (simpler):**

1. Create a **classic PAT** at https://github.com/settings/tokens  
   Required scopes: `repo` (clone), `read:packages` (pull Docker images from ghcr.io)  
2. Use it as your password when cloning (token is NOT your GitHub password):

```bash
git clone -b fix/installer-linux-windows-fixes https://github.com/mtrnix/metatroncore.git
# Username: your-github-username
# Password: ghp_xxxxxxxxxxxxxxxxxxxx  ← paste the token
```

Or cache it so you're not asked every time:
```bash
git config --global credential.helper store
```

**Option B — SSH key (no password prompts after setup):**

```bash
# 1. Generate key if you don't have one
ssh-keygen -t ed25519 -C "your@email.com"
# 2. Add public key to GitHub: https://github.com/settings/keys
cat ~/.ssh/id_ed25519.pub
# 3. Clone via SSH
git clone -b fix/installer-linux-windows-fixes git@github.com:mtrnix/metatroncore.git
```

**Verify access:** if `git clone` succeeds, your account has access.

### Docker (required)

Metronix Core runs entirely in Docker containers. You need Docker Engine (Linux) or Docker Desktop (macOS / Windows) installed and running.

| Platform | How to install | Verify |
|----------|---------------|--------|
| **Linux** | `curl -fsSL https://get.docker.com \| sh` — the installer offers this automatically | `docker info` |
| **macOS** | [Docker Desktop](https://www.docker.com/products/docker-desktop/) or `brew install --cask docker` | Launch Docker.app, wait for whale icon in menu bar |
| **Windows** | [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Launch from Start Menu, wait for tray icon → "Engine running" |

**Linux only:** add your user to the `docker` group to avoid `sudo`:
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### Git (all platforms)

- **Linux:** `sudo apt install git` / `sudo dnf install git`
- **macOS:** `brew install git` or `xcode-select --install`
- **Windows:** `winget install Git.Git` or https://git-scm.com/download/win

### Disk space

| Profile | Free space needed |
|---------|------------------|
| minimal | ~5 GB |
| full | ~15 GB (includes Ollama models) |
| custom | depends on selected services |

---

## Quick Start — Linux / macOS

```bash
# 1. Clone
git clone -b fix/installer-linux-windows-fixes https://github.com/mtrnix/metatroncore.git
cd metatroncore

# 2. Run
./install/bootstrap.sh
```

The script installs `uv` and Docker automatically if missing, then launches the wizard.

### What the wizard will ask

| Question | Options |
|----------|---------|
| **Deployment mode** | `server` (bind 0.0.0.0, accessible from network) / `local` (127.0.0.1, localhost only) |
| **LLM provider** | `deepseek` / `openrouter` / `ollama` / `custom` |
| **API key** | Required for deepseek/openrouter/custom |
| **Deployment profile** | `minimal` (core + UI :3000) / `full` (everything + UIs :3000 :3001 :3080) / `custom` |
| **Integrations** | Optional: OpenAI-compat key, MCP key, Telegram token |

### After install — UI endpoints

```
Metronix UI:      http://localhost:3000
Metronix UI CC:   http://localhost:3001   (full profile only)
Open WebUI:       http://localhost:3080   (full profile only)
Metronix API:     http://localhost:8000
```

> **Docker registry auth:** Docker images are hosted on `ghcr.io/mtrnix`. The installer first attempts an anonymous pull. If that fails (401), it will ask for your **GitHub username + PAT** (same token as for `git clone`, with `read:packages` scope) and run `docker login ghcr.io` automatically.

### Non-interactive mode (no questions)

```bash
./install/bootstrap.sh --non-interactive               # server + minimal + deepseek, no prompts
./install/bootstrap.sh --dry-run                        # preview .env, don't touch Docker
./install/bootstrap.sh --config answers.yaml            # read all settings from YAML
```

`answers.yaml` example:
```yaml
mode: server
profile: full
llm_provider: deepseek
llm_api_key: sk-your-key
integrations:
  openai_compat_key: my-key
```

### Working with an existing install

If `.env` or running containers are detected:

| Action | What it does |
|--------|-------------|
| `reconfigure` | Run wizard again, rewrite `.env`, pull images, restart stack |
| `restart` | `docker compose restart` — quick restart, no pull, keep config |
| `upgrade` | Pull fresh images, restart — keep current `.env` untouched |
| `uninstall` | Stop & remove containers (optionally delete images and data volumes) |

### Day-to-day management

```bash
docker compose -f install/docker-compose.yml ps           # service status
docker compose -f install/docker-compose.yml logs -f       # live logs
docker compose -f install/docker-compose.yml down          # stop containers
docker compose -f install/docker-compose.yml down --volumes # stop + delete all data
```

---

## Quick Start — Windows

```powershell
# 1. Allow script execution (one-time)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2. Clone
git clone -b fix/installer-linux-windows-fixes https://github.com/mtrnix/metatroncore.git
cd metatroncore

# 3. Run
.\install\bootstrap.ps1
```

Same wizard questions as Linux/macOS. Docker Desktop must be running (whale icon in system tray).

---

## Profiles

| Profile | Services | UI Ports |
|---------|----------|----------|
| **minimal** | postgres, qdrant, neo4j, redis, splade, metatron-core, freshness-worker + metatron-ui | `:3000` |
| **full** | core + ollama, embedding-proxy, metatron-ui, metatron-ui-cc, openwebui | `:3000` `:3001` `:3080` |
| **custom** | core + pick from: ollama, embedding-proxy, openwebui, metatron-ui, metatron-ui-cc | depends on selection |

Core = always-on services: postgres, qdrant, neo4j, redis, splade, metatron-core, freshness-worker.

---

## LLM Providers

| Provider | Requires |
|----------|----------|
| `ollama` | Bundled with full profile, or external host URL (minimal profile) |
| `deepseek` | API key |
| `openrouter` | API key |
| `custom` | API key + endpoint URL |

---

## Service Ports

| Service | Port |
|---------|------|
| Metronix API | 8000 |
| Metronix UI | 3000 |
| Metronix UI CC | 3001 |
| Open WebUI | 3080 |
| Ollama | 11435 |
| PostgreSQL | 5433 |
| Qdrant HTTP | 6335 |
| Qdrant gRPC | 6336 |
| Neo4j HTTP | 7475 |
| Neo4j Bolt | 7688 |
| Redis | 6379 |
| SPLADE | 8080 |
| Embedding Proxy | 8001 |
