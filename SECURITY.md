# Security Policy

## Reporting a Vulnerability

**Do not open a public issue.** Security vulnerabilities must be reported privately.

Email: `security@mtrnix.com` (preferred) or use GitHub's [private vulnerability reporting](https://github.com/mtrnix/metronix-memory/security/advisories/new).

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Affected versions (commit hash or release tag)
- Any proof-of-concept or exploit code (optional but helpful)
- Whether you'd like public credit

### Response Timeline

| Phase | Target |
|---|---|
| Acknowledgement | Within 24 hours |
| Triage and validation | Within 72 hours |
| Fix development | Within 7 days (critical), 30 days (moderate) |
| Coordinated disclosure | After fix is released and users have upgrade window |

### Disclosure Policy

We follow coordinated disclosure:
1. Fix is developed and tested
2. Release is cut with the fix
3. Advisory is published 7 days after release (to allow upgrades)
4. Reporter is credited unless they request anonymity

## Scope

Security coverage applies to:

- **Metronix Memory** — the API server, MCP server, ingestion/retrieval pipelines, memory service, connectors
- **Configuration** — `.env` handling, secrets management
- **Authentication** — JWT, API keys, workspace isolation
- **MCP transport** — stdio and streamable-http

### Out of Scope

- Third-party services connected via MCP (Jira, Confluence, etc.)
- User-managed LLM providers (Ollama, OpenRouter)
- Public demo instances
- Social engineering
- Denial-of-service via infinite queries (rate limiting is documented, not enforced)

## Supported Versions

| Version | Support |
|---|---|
| `develop` (latest) | ✅ Full support — security fixes land here first |
| Latest release tag | ✅ Security backports |
| Older releases | ❌ Upgrade to latest |

## Security Best Practices for Deployers

1. **Never expose** the API or MCP server to the public internet without a reverse proxy + TLS.
2. **Rotate API keys** regularly. Use per-workspace keys with minimal scope.
3. **Audit** your `.env` file — no defaults in production. All passwords must be unique.
4. **Restrict** database ports (PostgreSQL, Qdrant, Neo4j, Redis) to Docker network — use `127.0.0.1:` bindings.
5. **Enable** `AUTH_ENABLED=true` in production — this gates all endpoints behind JWT.
6. **Monitor** `make test` output for any security-related test failures after upgrades.

## Hall of Fame

We maintain a public acknowledgment list for security researchers who responsibly disclose vulnerabilities (with their permission). Contact us after your fix is released to be added.
