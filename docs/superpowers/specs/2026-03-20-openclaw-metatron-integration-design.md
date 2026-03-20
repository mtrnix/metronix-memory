# OpenClaw → Metatron Integration Design

**Date:** 2026-03-20
**Status:** Draft
**Goal:** Connect OpenClaw (personal AI assistant) to Metatron (corporate RAG system) as a knowledge base via MCP.

## Overview

OpenClaw is a self-hosted personal AI assistant deployed on Server A.
Metatron is a corporate RAG system deployed on Server B.

The OpenClaw agent should search for answers in Metatron's corporate knowledge base. Starting with the `metatron_search` tool and a single workspace.

```
OpenClaw (Server A) → HTTP → Metatron /mcp (Server B)
```

Two integration options:
- **Option A** — `mcp-remote` (native MCP tools) — recommended
- **Option B** — `MCPorter` (CLI + skill + daemon)

## Prerequisites: Metatron Setup

### 1. Fix /mcp Authentication (DONE)

During investigation it was discovered that `METATRON_MCP_API_KEY` was **not validated**
for the `/mcp` endpoint when running via `create_app()` (the standard mode). Validation
only worked in standalone `run_http()` mode.

**Fix:** branch `fix/mcp-api-key-auth` — middleware now intercepts `/mcp` independently
of `AUTH_ENABLED` and validates via `METATRON_MCP_API_KEY`. Also switched to timing-safe
key comparison (`hmac.compare_digest`).

**Status:** fix implemented and tested (6 tests), pending merge.

### 2. Configure API Key

```bash
# In .env or Metatron environment variables
METATRON_MCP_API_KEY=your-secure-key-here
```

Without this, MCP accepts all requests without authentication (dev mode).

### 3. Ensure /mcp is Accessible Externally

Metatron supports streamable-http transport at `/mcp`.
Ensure the endpoint is reachable from the OpenClaw server (firewall, reverse proxy).

### 4. Get Workspace ID

MCP tools accept `workspace_id` as a parameter. Retrieve the target workspace ID:

```bash
curl https://metatron-server:8000/api/v1/workspaces
```

### 5. Verify Connectivity

```bash
curl -H "Authorization: Bearer your-secure-key-here" \
     https://metatron-server:8000/mcp
```

## Option A: mcp-remote (Recommended)

### What It Is

An npm package that OpenClaw launches as a stdio subprocess. Internally it opens
an HTTP connection to the remote MCP server. No separate process to manage.

- **GitHub:** https://github.com/geelen/mcp-remote (1,300+ stars)
- **Requirements:** Node.js (npx) on the OpenClaw server

### How It Works

1. OpenClaw agent decides to call the `metatron_search` tool
2. OpenClaw spawns `npx mcp-remote` as a subprocess (stdio)
3. `mcp-remote` opens an HTTP connection to Metatron `/mcp`
4. Proxies the request, returns the response via stdio
5. Subprocess stays alive while OpenClaw holds the session

The agent sees Metatron tools as **its own native tools** — it does not know
there is a proxy behind them. No special prompting needed.

### Configuration

In `openclaw.json` on the OpenClaw server:

```json
{
  "mcp": {
    "servers": {
      "metatron": {
        "command": "npx",
        "args": [
          "-y", "mcp-remote",
          "https://metatron-server:8000/mcp",
          "--header", "Authorization:Bearer ${METATRON_MCP_KEY}"
        ],
        "env": {
          "METATRON_MCP_KEY": "your-secure-key-here"
        }
      }
    }
  }
}
```

### Verification

```bash
openclaw gateway restart
openclaw mcp list
openclaw mcp show metatron
```

The agent should see: `metatron_search`, `metatron_get`, `metatron_store`,
`metatron_sync`, `metatron_status`.

### Test

Send the agent a message on any channel:
> "Find information about VPN in the knowledge base"

The agent will automatically call `metatron_search` and return an answer with sources.

### Latency

- First launch: ~2-3 sec (npx downloads the package)
- Subsequent: ~200-500ms (package cached)
- HTTP to Metatron: ~50-200ms (depends on network)

### Limitations

- No persistent connection — subprocess is recreated per session
- OpenClaw currently supports stdio MCP only — `mcp-remote` bridges this gap

## Option B: MCPorter

### What It Is

A CLI tool + daemon for working with MCP servers. Built-in as a skill in OpenClaw.

- **GitHub:** https://github.com/steipete/mcporter
- **Requirements:** Node.js + `npm install -g mcporter`

### How It Works

The agent uses the built-in `mcporter` skill and invokes CLI commands. The agent
must **consciously decide** to use mcporter — this requires a skill prompt that
explains when and how to call Metatron.

### Installation

```bash
npm install -g mcporter
```

### Configuration

In `~/.mcporter/mcporter.json` or `config/mcporter.json`:

```json
{
  "servers": {
    "metatron": {
      "url": "https://metatron-server:8000/mcp",
      "headers": {
        "Authorization": "Bearer your-secure-key-here"
      }
    }
  }
}
```

### Verification

```bash
mcporter list metatron
mcporter call metatron.metatron_search query="VPN" workspace_id="your-workspace-id"
```

### Daemon (Persistent Connection)

```bash
mcporter daemon start    # keeps the connection warm
mcporter daemon status   # check connection
mcporter daemon stop     # stop daemon
```

### Limitations

- Tools are not native MCP tools — calls go through CLI
- Agent must "know" about mcporter via skill prompt
- Dependency on a separately installed package

## Comparison

| Criteria | mcp-remote | MCPorter |
|----------|-----------|---------|
| **Setup simplicity** | Simpler — OpenClaw config only | Install + config + skill |
| **Agent nativeness** | Native MCP tools | CLI via skill |
| **Token cost** | ~150-250 per call | ~700-1400 per call (3-5x more) |
| **Extensibility** | Automatic — new tools appear instantly | Skill update needed |
| **Persistent connection** | No (reconnect ~200-500ms) | Yes (daemon) |
| **Debugging** | Less transparent | Easier (CLI) |
| **Agent awareness** | Not needed, sees tools natively | Requires skill prompt |

### Token Cost Details

**mcp-remote:** tool definition in system prompt as JSON-schema (~100-200 tokens
per tool), call is a standard tool_use block (~30-50 tokens). Total ~150-250 per call.

**MCPorter:** skill loaded into prompt (~500-1000 tokens), CLI command generation +
response parsing (~100-200 tokens), reasoning about syntax (~50-200 tokens). Total ~700-1400.

## Recommendations

**When to choose mcp-remote:**
- Primary production scenario
- Token cost matters
- Set-and-forget deployment

**When to choose MCPorter:**
- Persistent connection needed (high load, latency-critical)
- Debugging calls from CLI before handing to agent
- Managing multiple MCP servers via unified CLI

**Recommendation:** start with **mcp-remote** as the primary option. Use MCPorter
for debugging and as a fallback when daemon is needed.

## Available Metatron Tools (MCP)

| Tool | Description |
|------|-------------|
| `metatron_search` | Hybrid RAG search (vector + BM25 + graph) |
| `metatron_get` | Fetch a specific document by ID |
| `metatron_store` | Index a new document |
| `metatron_sync` | Trigger connector sync |
| `metatron_status` | Workspace statistics |

Starting with `metatron_search`, expanding as needed.

## Known Issues

- **AUTH_ENABLED** — consider removing this env variable in a separate task.
  Currently `AUTH_ENABLED=false` by default, but login still works via UI
  (middleware simply skips JWT validation). This creates confusion.
