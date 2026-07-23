# Metronix Admin Console

The **Metronix Admin Console** is the open-source web UI for administering a Metronix Core
instance: connect data sources, register chat-bot channels, upload files, and watch the
health of the stack. It is a thin presentation layer — all logic and persistence live in
`metronix-core`, which the console reaches over the REST API.

The console is **optional**. The backend runs fully headless (MCP + REST); the console just
gives you a UI on top of it.

> **Scope:** this is the open-source admin console. The full operational **Control Center**
> (agent registry, workflow builder, memory inspector, FinOps, multi-team admin) is a separate
> product and is not part of this repository.

## What you can do here

- **Sources** — add, test, and sync **data connectors** (Jira, Confluence, GitHub, Google
  Drive, Notion, Slack) and **chat-bot channels** (Telegram, Discord, Slack), plus upload
  files for indexing.
- **Health & Stats** — service and database status (Postgres, Qdrant, Neo4j, Redis), workspace
  statistics, and live metrics.

## Prerequisites

- A running `metronix-core` instance on `http://127.0.0.1:8000` (see the repo root
  [`install.md`](../install.md) to bring up the full stack).
- For local development: Node.js 20+.

## Run with Docker (recommended)

The console ships as an optional service behind the `admin` Docker Compose profile. From the
repo root:

```bash
docker compose --profile admin up -d --build
```

Then open **https://localhost:3000**. The container is a **Caddy** image that serves the built
SPA over **HTTPS** and proxies `/api`, `/health`, `/ready`, and `/metrics` to
`metronix-core:8000`. Its Docker-visible container name is
`metronix-memory-frontend`.

By default Caddy uses its **internal CA** (self-signed). Your browser will warn about an
untrusted certificate — accept it once for local use, or install the Caddy root CA into your
trust store for a quieter experience.

Override the published port with `ADMIN_FRONTEND_PORT` (default `3000`):

```bash
ADMIN_FRONTEND_PORT=3100 docker compose --profile admin up -d
```

### Switching to automatic Let's Encrypt (public domain)

For a real domain the console can auto-provision a trusted certificate via Let's Encrypt:

1. Set `CADDY_DOMAIN=your-domain.com` (must resolve to this host).
2. Publish ports 80 and 443 instead of `:3000`, e.g.:
   ```yaml
   ports:
     - "80:80"
     - "443:443"
   ```
3. Edit `frontend/Caddyfile` and remove the `tls internal` line — Caddy will then auto-issue
   and renew a Let's Encrypt certificate.

## Run for development

```bash
cd frontend
npm install
npm run dev            # Vite dev server → http://127.0.0.1:3000
```

The dev server proxies `/api`, `/health`, `/ready`, `/metrics` to `http://127.0.0.1:8000`,
so point it at a running backend.

Default development credentials: `admin@metronix.local` / `metronix`.

## Build

```bash
npm run build          # type-check + Vite production build → frontend/dist/
npm run preview        # serve the production build locally
npm run lint           # ESLint
```

## Tech stack

React 19 · TypeScript 5.9 (strict) · Vite 7 · Tailwind CSS v4 (dark theme) · TanStack Query v5
· Zustand v5 · React Router v7. Auth is a JWT bearer token kept in `sessionStorage`; every API
call carries the active workspace via that token.
