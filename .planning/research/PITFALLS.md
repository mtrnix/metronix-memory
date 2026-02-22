# Pitfalls Research

**Domain:** MCP Server + OpenClaw Integration + One-Line Installer
**Researched:** 2026-02-22
**Confidence:** HIGH

---

## Critical Pitfalls

### Pitfall 1: STDIO Transport Logging Corruption

**What goes wrong:**
Any `print()` or `stdout` write in an MCP server corrupts the JSON-RPC protocol stream. The client receives malformed messages and fails silently or with cryptic errors.

**Why it happens:**
STDIO transport uses stdout exclusively for protocol messages. Developers instinctively use `print()` for debugging, not realizing it pollutes the message channel.

**How to avoid:**
- Configure all logging to stderr BEFORE any server code runs
- Use `logging.basicConfig(stream=sys.stderr)` or structlog with stderr handler
- Add a CI check that fails if `print(` appears in server code
- Never use `print()` — always use structured logging

**Warning signs:**
- "Invalid JSON" errors from MCP client
- Client hangs waiting for response
- Intermittent failures after adding "debugging"

**Phase to address:** Phase 1 (MCP Server Core)

---

### Pitfall 2: Token Passthrough Anti-Pattern

**What goes wrong:**
Server accepts raw user tokens and forwards them to downstream services. This breaks audit trails, bypasses rate limits, and creates "confused deputy" security vulnerabilities.

**Why it happens:**
It's the fastest way to get "auth working" — just pass through whatever token the client sends.

**How to avoid:**
- Server MUST obtain its own tokens for downstream services
- Validate `aud` claim on incoming tokens — reject if not intended for your server
- Map user identity to server-scoped credentials
- Never log or store raw tokens

**Warning signs:**
- Auth works but audit logs show wrong source
- Rate limiting doesn't work per-user
- Token appears in server logs

**Phase to address:** Phase 1 (MCP Server Core — Auth)

---

### Pitfall 3: Tool Selection Confusion from Poor Naming

**What goes wrong:**
LLM calls the wrong tool, calls tools with wrong parameters, or refuses to call tools that fit the task. Users see "the AI is broken."

**Why it happens:**
- Tool names overlap conceptually (`search` vs `query` vs `find`)
- Descriptions are vague ("Searches the database")
- Too many similar tools confuse the model

**How to avoid:**
- Use distinct, action-oriented names: `metatron_search_docs`, `metatron_get_chunk`, `metatron_store_memory`
- Write descriptions that explain WHEN to use, not just WHAT it does
- Apply Single Responsibility Principle to tools — one job per tool
- Keep tool count under 10-15 per server if possible
- Test tool selection with multiple LLM providers

**Warning signs:**
- LLM explains why it CAN'T do something that a tool provides
- LLM calls `search` when user asked to `store`
- Different LLM providers behave differently with same tools

**Phase to address:** Phase 1 (MCP Server Core — Tool Design)

---

### Pitfall 4: curl | bash Installer Blind Execution

**What goes wrong:**
Users run `curl http://app.mtrnix.com | bash` without reviewing the script. If the server is compromised or MITM'd, attackers get RCE on every installer.

**Why it happens:**
It's the de facto standard for "easy install" (Homebrew, nvm, rustup). Users are trained to trust it.

**How to avoid:**
- Serve script over HTTPS ONLY
- Provide checksum/signature verification option
- Document: "Review before running: curl ... > install.sh && less install.sh && bash install.sh"
- Include version pinning in the script itself
- Consider `curl | LESS` pattern for forced review
- Host on CDN with integrity headers

**Warning signs:**
- No HTTPS on installer URL
- Script pulls more code from internet at runtime
- No version visible in script

**Phase to address:** Phase 3 (Installer)

---

### Pitfall 5: Multi-Service Startup Race Conditions

**What goes wrong:**
Docker Compose starts services in parallel. Metatron API starts before Qdrant/Memgraph/Postgres are ready, fails health checks, and crashes. Users see "service won't start" with no clear error.

**Why it happens:**
`depends_on` only waits for container to START, not be HEALTHY. Network race conditions between services.

**How to avoid:**
- Use `healthcheck` in docker-compose.yml for all dependencies
- Use `depends_on: condition: service_healthy`
- Implement retry logic with exponential backoff in Metatron startup
- Add `/ready` endpoint that checks all dependencies
- Log which service caused startup failure

**Warning signs:**
- "Connection refused" errors on first start
- Services work after `docker compose restart`
- Intermittent failures on slow machines

**Phase to address:** Phase 4 (Full Stack Installer)

---

### Pitfall 6: Response Token Bloat

**What goes wrong:**
Tool responses dump entire documents or large JSON structures into the LLM context window. Token costs explode, responses get truncated, model "loses" earlier context.

**Why it happens:**
Developers test with small documents. Production data is 100x larger. No one thinks about token limits until the bill arrives.

**How to avoid:**
- Paginate all list operations with reasonable defaults (10-50 items)
- Summarize large documents before returning (secondary LLM call)
- Truncate text fields with "..." and offer `get_full` tool
- Add `max_tokens` parameter to tools
- Log response token counts

**Warning signs:**
- API costs spike unexpectedly
- LLM responses become incoherent after tool use
- "Context too long" errors from LLM provider

**Phase to address:** Phase 1 (MCP Server Core — Tool Responses)

---

### Pitfall 7: SSE Transport is Deprecated

**What goes wrong:**
Project builds SSE-based MCP server because tutorials show it. Later discovers SSE is deprecated in favor of Streamable HTTP. Forced rewrite.

**Why it happens:**
Old blog posts and examples still show SSE. The spec evolved but documentation didn't catch up.

**How to avoid:**
- Use Streamable HTTP (`transport="streamable-http"`) for remote servers
- Use STDIO for local subprocess servers
- Avoid SSE entirely for new projects

**Warning signs:**
- Server config has `transport="sse"`
- Tutorial/blog post dated before 2025

**Phase to address:** Phase 1 (MCP Server Core — Transport Choice)

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Single shared token for all users | Fast auth implementation | No per-user audit, rate limit bypass, confused deputy | Never |
| No healthchecks in compose | Simpler YAML | Race conditions, flaky starts | Never |
| Skip input validation | Faster tool development | SQL injection, prompt injection, RCE | Never |
| Hardcoded ports | Works on my machine | Conflicts, can't run multiple instances | Dev only |
| Skip pagination | Simpler response code | Token bloat, cost explosion | Docs < 100 items |
| curl \| bash without checksum | One-liner install | MITM, compromised server = RCE | Never |
| Global state in tools | Easier caching | Multi-user data leaks, race conditions | Never |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| OpenClaw MCP Client | Assuming stdio transport only | Support both stdio and streamable-http; test both |
| Qdrant | No quantization, memory explosion | Configure scalar quantization, set memory limits |
| Memgraph | No connection pooling | Use connection pool, handle stale connections with retry |
| PostgreSQL | Missing migration rollback | Every migration needs working `upgrade()` AND `downgrade()` |
| Docker Compose | Using `depends_on` without healthchecks | Add healthcheck + `condition: service_healthy` |
| OAuth (future) | Token passthrough | Server obtains own tokens, validates audience |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Vector search without indexing | 500ms+ query times, CPU spikes | Create HNSW index, tune ef/m params | >10k vectors |
| No embedding cache | Same docs re-embedded on every sync | Cache embeddings by content hash | >1000 docs |
| Unbounded tool response | Token limit exceeded, cost spikes | Paginate, summarize, truncate | >5k chars response |
| Sync on every startup | 30s+ startup, API rate limits | Store sync state, incremental only | >10k documents |
| Memgraph query timeout | Queries hang forever | Set query timeout, add indexes | Complex graph queries |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Exposing MCP server on 0.0.0.0 | Anyone on network can call tools | Bind to localhost, use reverse proxy with auth |
| No auth on MCP server | Anonymous access to all tools | Require token validation on every request |
| Tool calling itself (loop) | Infinite loop, resource exhaustion | Detect tool cycles, set max call depth |
| Prompt injection via stored data | Attacker embeds commands in docs | Sanitize/sandbox data before LLM context |
| Third-party MCP server trust | Malicious server gets full access | Review code, sandbox, limit permissions |
| Installer script without checksum | MITM replaces script | HTTPS + SHA256 verification |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Installer fails silently | User thinks it worked, nothing running | Verbose progress, clear success/failure message |
| "Service won't start" error | No actionable information | List which service failed and why |
| Config requires manual editing | Typos break everything | Interactive config wizard or env-file only |
| No uninstall path | Orphaned containers/volumes | `./install.sh --uninstall` that cleans everything |
| Missing dependency error | "Command not found" frustration | Check dependencies upfront with install instructions |

---

## "Looks Done But Isn't" Checklist

- [ ] **MCP Server:** Often missing proper error responses — verify tools return structured errors, not exceptions
- [ ] **Auth:** Often missing token audience validation — verify server rejects tokens not meant for it
- [ ] **Docker Compose:** Often missing healthchecks — verify services wait for healthy dependencies
- [ ] **Installer:** Often missing idempotency — verify running twice doesn't break
- [ ] **Uninstall:** Often missing entirely — verify cleanup removes all containers/volumes/networks
- [ ] **Tool Descriptions:** Often too vague — verify LLM selects correct tool without hints
- [ ] **Error Messages:** Often unhelpful — verify errors include "what to do next"

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| STDIO logging corruption | LOW | Redirect all logging to stderr, redeploy |
| Token passthrough | MEDIUM | Add server-side token acquisition, migrate users |
| Tool naming confusion | MEDIUM | Rename tools, update descriptions, redeploy |
| curl \| bash compromise | HIGH | Revoke all credentials, incident response, new installer |
| Startup race conditions | LOW | Add healthchecks, redeploy |
| Response bloat | LOW | Add pagination/summarization, redeploy |
| SSE deprecation | MEDIUM | Rewrite to streamable-http |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| STDIO logging corruption | Phase 1 (MCP Server Core) | CI check for print() in server code |
| Token passthrough | Phase 1 (MCP Server Core) | Security review of auth flow |
| Tool naming confusion | Phase 1 (MCP Server Core) | LLM tool selection tests with multiple providers |
| curl \| bash security | Phase 3 (Installer) | HTTPS-only, checksum documented |
| Multi-service race conditions | Phase 4 (Full Stack) | Test cold start on slow machine |
| Response token bloat | Phase 1 (MCP Server Core) | Test with 100KB+ documents |
| SSE deprecation | Phase 1 (MCP Server Core) | Verify transport="streamable-http" |
| OpenClaw config helper | Phase 2 (Integration) | Test with stock OpenClaw installation |

---

## Sources

- NearForm: "Implementing MCP: Tips, Tricks and Pitfalls" (Dec 2025) — HIGH confidence
- Hailey Quach: "MCP Security Survival Guide" (Aug 2025) — HIGH confidence
- Trend Micro: "MCP Security: Network-Exposed Servers" (2025) — HIGH confidence
- Context7: Model Context Protocol Python SDK docs — HIGH confidence
- Docker Docs: "Control startup order in Compose" (2025) — HIGH confidence
- Various: curl | bash security discussions (2024-2025) — MEDIUM confidence

---
*Pitfalls research for: MCP Server + OpenClaw Integration + One-Line Installer*
*Researched: 2026-02-22*
