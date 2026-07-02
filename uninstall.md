# Uninstalling Metronix Core

This guide fully removes a Metronix Core deployment installed with `./install.sh` (or by
hand via [`install.md`](install.md)). It walks from "stop the stack" to "leave no trace":
Docker containers, networks, volumes (your data), built images, the generated `.env`, and
any AI-agent wiring (e.g. Hermes) that the installer added outside this repository.

Work from the repository root — the directory containing `docker-compose.yml`. The
Compose **project name** defaults to that directory's name — `metronix-memory` for a standard
`git clone`. The resource names below assume that prefix; if your clone directory differs (or
you set `COMPOSE_PROJECT_NAME`), substitute it accordingly.

> **Pick your depth.** Stopping the stack (step 1) is reversible. Removing volumes (step 2)
> **deletes all stored memory, embeddings, and graph data permanently** — there is no undo.
> Steps 3–5 reclaim disk and clean up files the installer wrote elsewhere.

## What the installer created

`./install.sh` produces artifacts in three places:

| Where | Artifact |
|---|---|
| Docker — containers | `metronix-full-{api,postgres,qdrant,neo4j,redis,ollama,splade}` (+ `-openwebui`, `-embedding-proxy` if those profiles were used) |
| Docker — network | `metronix-memory_metronix_full` |
| Docker — volumes (data) | `metronix-memory_full_{pg,qdrant,neo4j,redis,ollama,file}_data` (+ `_openwebui_data`) |
| Docker — built images | `metronix-memory-metronix-core`, `metronix-memory-splade` (+ `metronix-memory-embedding-proxy`) |
| Docker — pulled images | `postgres:16-alpine`, `qdrant/qdrant:v1.18.0`, `neo4j:5-community`, `redis:7-alpine`, `ollama/ollama:latest` (+ `ghcr.io/open-webui/open-webui:main`) |
| Repo root | `.env` (generated secrets); `metronix-hermes-setup/`, `metronix-claude-code-setup/`, `metronix-codex-setup/`, `metronix-openclaw-setup/`, `metronix-agent-setup/` (filled agent-setup prompts — whichever runtime(s) you wired) |
| `~/.hermes/` | `config.yaml` (`mcp_servers.metronix` block), `SOUL.md` (`--- metronix-config ---` block), plus `*.bak-<timestamp>` backups |

## 1. Stop the stack (reversible)

Stops and removes containers and the network, but **keeps volumes** — your data survives and
`./install.sh` (or `docker compose up`) brings everything back.

```bash
docker compose down
```

`down` removes every container in the project regardless of which `--profile` it was started
with, so no profile flags are needed here.

To merely pause without removing containers, use `docker compose stop`.

## 2. Remove data volumes (destructive, no undo)

Add `-v` to also delete the named volumes. This wipes Postgres, Neo4j, Qdrant, Redis, the
Ollama model cache, and uploaded files.

```bash
docker compose down -v
```

Verify nothing is left for the project:

```bash
docker ps -a                       # no metronix-full-* containers
docker volume ls | grep metronix-memory   # no metronix-memory_full_* volumes
```

If a volume lingers (e.g. it was created under a different project name), remove it by name:

```bash
docker volume rm metronix-memory_full_pg_data metronix-memory_full_neo4j_data \
                 metronix-memory_full_qdrant_data metronix-memory_full_redis_data \
                 metronix-memory_full_ollama_data metronix-memory_full_file_data \
                 metronix-memory_full_openwebui_data
```

## 3. Remove images (reclaim disk)

**Locally built images** — delete these to force a clean rebuild on the next install:

```bash
docker rmi metronix-memory-metronix-core:latest metronix-memory-splade:latest
docker rmi metronix-memory-embedding-proxy:latest 2>/dev/null || true   # only if benchmarker profile was used
```

**Pulled base images** — optional. Keeping them makes the next install faster (no re-download);
removing them frees ~8 GB. Only delete if no other project uses them:

```bash
docker rmi postgres:16-alpine qdrant/qdrant:v1.18.0 neo4j:5-community \
           redis:7-alpine ollama/ollama:latest
docker rmi ghcr.io/open-webui/open-webui:main 2>/dev/null || true    # only if openwebui profile was used
```

To clean leftover dangling layers and build cache:

```bash
docker image prune -f
docker builder prune -f
```

## 4. Remove generated repo files

The installer writes these into the repo root. `.env` is git-ignored;
`metronix-hermes-setup/`, `metronix-claude-code-setup/`, `metronix-codex-setup/`,
`metronix-openclaw-setup/`, and `metronix-agent-setup/` are generated directories (filled
setup prompts, for whichever runtime(s) you wired) you can safely delete. Removing them only
affects your local deployment:

```bash
rm -f .env
rm -rf metronix-hermes-setup/ metronix-claude-code-setup/ metronix-codex-setup/ metronix-openclaw-setup/ metronix-agent-setup/
```

> Keep `.env` if you plan to reinstall and want to preserve your secrets, database
> passwords, and the persisted agent id (`METRONIX_AGENT_ID`) — `./install.sh` reuses an
> existing `.env` unless you pass `--reconfigure`.

## 5. Remove the MCP agent wiring (Hermes)

If you ran `--connect-hermes` (or accepted the prompt at the end of install), the installer
edited your Hermes config **outside this repository**. It always backs up each file first to
`<file>.bak-<timestamp>`, so the cleanest revert is to restore that backup.

**Option A — restore the pre-install backup (recommended):**

```bash
ls -t ~/.hermes/config.yaml.bak-* ~/.hermes/SOUL.md.bak-* 2>/dev/null   # find the newest backups
cp ~/.hermes/config.yaml.bak-<timestamp> ~/.hermes/config.yaml
cp ~/.hermes/SOUL.md.bak-<timestamp>     ~/.hermes/SOUL.md
```

**Option B — edit by hand** (if no backup exists or you changed the files since):

1. In `~/.hermes/config.yaml`, delete the `metronix:` entry under `mcp_servers:`:

   ```yaml
   mcp_servers:
     metronix:               # <-- delete this whole block
       url: http://localhost:8000/mcp
       headers:
         Authorization: "Bearer ..."
         X-Agent-Id: ...
       timeout: 180
       connect_timeout: 60
   ```

2. In `~/.hermes/SOUL.md`, delete the block delimited by these markers (inclusive):

   ```
   --- metronix-config ---
   ... (lines between) ...
   --- end metronix-config ---
   ```

3. Restart Hermes so it reloads its MCP client list: `/quit`, then `hermes`.

Once you have confirmed Hermes works, the timestamped backups can be deleted:

```bash
rm -f ~/.hermes/config.yaml.bak-* ~/.hermes/SOUL.md.bak-*
```

> The agent's stored memories live inside Metronix (removed with the volumes in step 2), not
> in the Hermes config — these edits only disconnect the agent.

## One-shot full removal

Destructive — wipes data, built images, generated files, and Hermes wiring in one go. Review
each line before running:

```bash
# From the repo root
docker compose down -v
docker rmi metronix-memory-metronix-core:latest metronix-memory-splade:latest 2>/dev/null || true
rm -f .env
rm -rf metronix-hermes-setup/ metronix-claude-code-setup/ metronix-codex-setup/ metronix-openclaw-setup/ metronix-agent-setup/
# Hermes: restore the newest backup if present (see step 5 for the by-hand alternative)
cfg=$(ls -t ~/.hermes/config.yaml.bak-* 2>/dev/null | head -1); [ -n "$cfg" ] && cp "$cfg" ~/.hermes/config.yaml
soul=$(ls -t ~/.hermes/SOUL.md.bak-* 2>/dev/null | head -1); [ -n "$soul" ] && cp "$soul" ~/.hermes/SOUL.md
```

Base images and the repo clone are left in place; remove them separately (step 3, and
`rm -rf` the clone) if you want nothing left at all.
