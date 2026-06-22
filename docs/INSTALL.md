# Installation Guide

Metatron Core is a multi-service stack (PostgreSQL, Qdrant, Neo4j, Redis, the API, SPLADE,
freshness worker, and optionally Ollama / embedding-proxy / OpenWebUI) orchestrated by Docker
Compose. The cross-platform installer is a terminal wizard that checks prerequisites, collects
configuration, writes `.env`, and brings the stack up.

## Prerequisites

- **Docker** + Docker Compose v2 (the only hard requirement). The installer detects Docker and
  guides you if it is missing or not running — it does **not** install Docker for you.
- Everything else (Python, `uv`) is bootstrapped automatically.
- A modern terminal. On Windows use Windows Terminal / PowerShell 5.1+.

## Quick install

**Linux / macOS:**
```bash
curl -fsSL https://app.mtrnix.com/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://app.mtrnix.com/install.ps1 | iex
```

The bootstrap ensures `uv` + Python, then runs `python -m metatron_installer`. It works the same
on a headless server over SSH as on a local machine.

### From a cloned repo

```bash
git clone https://github.com/mtrnix/metatroncore.git
cd metatroncore
bash install/bootstrap.sh          # Linux/macOS
# or, on Windows:
# pwsh install/bootstrap.ps1
```

## What the wizard asks

The steps run in this order (LLM provider is asked before profile, because choosing self-hosted
Ollama changes which services must run):

1. **Preflight** — OS detection, Docker presence + daemon reachable, and port conflicts across all
   published host ports (5433, 6335/6336, 7475/7688, 8000, 8001, 8080, 6379, 3000/3001, 3080, 11435).
   A missing/unreachable Docker aborts; port conflicts are warnings.
2. **Mode** — `server` (bind `0.0.0.0`) or `local` (bind `127.0.0.1`).
3. **LLM provider** — `ollama` / `deepseek` / `openrouter` / `custom`. An API key is requested only
   for providers that need one.
4. **Profile** — see below. `minimal` + `ollama` requires an external Ollama host (the wizard asks
   for it, or you can switch to `full`).
5. **Secrets** — Fernet key, Postgres password, and Neo4j password are generated automatically
   (strong by default; you can override).
6. **Integrations** (optional, opt-in) — OpenAI-compat key, MCP key, bot tokens.
7. **Registry** — images are pulled anonymously first; if the registry is private, you are prompted
   for a GitHub token and `docker login` is run before retrying the pull.
8. **Render + launch** — `.env` is written atomically, then `docker compose pull` + `up -d`,
   followed by a health-status table (snapshot of `docker compose ps`).

## Profiles

| Profile | Services | Use |
|---|---|---|
| `minimal` | postgres, qdrant, neo4j, redis, metatron-core, splade, freshness-worker | Backend only; LLM + embeddings are **external**. Lean server deploy. |
| `full` | `minimal` + ollama + embedding-proxy + open-webui | Self-contained; first run downloads ~5 GB of Ollama models. |
| `custom` | `minimal` base + per-service toggles | Pick optional services individually. |

The separate `metatron-ui` / `metatron-ui-cc` frontends live behind a `ui` profile and are not
started by `minimal` or `full` (deferred).

Internally the profile maps to the Docker `COMPOSE_PROFILES` env var written into `.env`.

## Non-interactive / automated installs

Provide all answers in a YAML file and skip prompts — useful for CI and repeatable server deploys.

```bash
bash install/bootstrap.sh --config answers.yaml --non-interactive
```

Render artifacts without launching Docker (CI smoke check):

```bash
bash install/bootstrap.sh --non-interactive --dry-run
```

Sample `answers.yaml`:

```yaml
mode: server
profile: full
llm_provider: deepseek
llm_api_key: sk-...        # or supply via env to keep it out of the file
ollama_host: ""            # required only for profile=minimal + llm_provider=ollama
integrations:
  openai_compat_key: ""
  mcp_api_key: ""
registry:
  github_user: ""          # only needed if the image registry is private
  github_token: ""
```

Secrets (Fernet key, Postgres/Neo4j passwords) are intentionally **not** read from the answers
file — they are generated at render time.

## Re-running the installer

Re-running detects an existing install (`.env` present and/or running `metatron-full-*` containers)
and offers:

- **reconfigure** — re-run the wizard, merging into the existing `.env` per key.
- **restart** — `docker compose restart`.
- **upgrade** — re-pull newer image tags and recreate.
- **uninstall** — `docker compose down` (optionally removing named volumes — explicit confirm).

`.env` is never silently overwritten.

## Troubleshooting

- **"Docker daemon not running"** — start Docker Desktop, or `sudo systemctl start docker`.
- **Port conflict** — the installer names the conflicting port and service; stop the other process
  or change the host-port mapping in `install/docker-compose.yml`.
- **Registry authentication (401/403)** — the registry is private; provide a GitHub username + token
  when prompted (or set `registry.github_user` / `registry.github_token` in `answers.yaml`).
- **Stack failed to start** — inspect logs: `docker compose -f install/docker-compose.yml logs -f`.
- **First `full` run is slow** — Ollama pulls ~5 GB of models on first boot; subsequent runs reuse
  the `full_ollama_data` volume.

## Manual setup

If you prefer to configure by hand, see the **Manual Setup** section in the project `README.md`.
