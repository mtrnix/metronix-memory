# Contributing to Metronix Core

Thanks for wanting to help. Metronix Core is an open-core AI memory + knowledge infrastructure. We welcome contributions.

## Getting Started

1. **Fork** the repo and clone your fork.
2. **Run the checks** before touching anything — see
   [Running checks locally](#running-checks-locally).

## Running checks locally

The same checks run on every pull request: **ruff** (lint + format) and **pytest**
(unit suite). Run them before pushing.

**Format & lint** — fast, no services needed. This is what the lint gate enforces:

```bash
make format   # ruff --fix + ruff format (auto-fixes what it can)
make lint     # ruff check + ruff format --check (CI runs exactly this)
```

Prefer it automatic? Install the git hooks (runs ruff on every commit):

```bash
uv run pre-commit install
```

**Tests** — the unit suite talks to real databases (Postgres, Neo4j, Qdrant,
Redis), so those must be reachable before running. The easiest, most reliable
path is to **let the PR's `Tests` workflow run them** against ephemeral service
containers — just push your branch.

To run them locally, point the `POSTGRES_*` / `NEO4J_*` / `QDRANT_*` / `REDIS_*`
env vars at running services, apply the schema, then run pytest. The exact
services, env, and migration step CI uses are in
[`.github/workflows/tests.yml`](.github/workflows/tests.yml) — mirror that:

```bash
make migrate   # alembic upgrade head — create the schema
make test      # pytest -m "not integration"
```

> Note: `make docker-up` starts the bundled stack on non-default host ports
> (Postgres `5433`, Neo4j `7688`, …), so set the matching `*_PORT` env vars, or
> run plain DB containers on the default ports, before `make test`.

**Type check** — `make typecheck` (mypy). Not a required gate yet.

## Architecture Constraint

Metronix has a **strict L0–L6 one-way dependency architecture**: a layer may
import only the same or a lower layer, never upward.

```text
L6  api/            REST, OpenAI-compatible, and MCP HTTP endpoints
L5  channels/       Telegram, Discord, and Slack integrations
L4  agent/          Intent routing and compatibility shims
L3  services/       Connectors, LLM, MCP, memory, auth, and workspaces
L2  processing/     Ingestion, retrieval, and freshness pipelines
L1  storage/        PostgreSQL, Qdrant, Neo4j, and Redis clients
L0  core/           Config, models, events, and plugin interfaces
```

Before adding an import, identify both layers and keep the dependency pointed
downward. If it would point upward, move the shared abstraction to a lower
layer instead.

## Workflow

```
Fork → Branch → Code → Test → Lint → PR
```

1. **Branch** from `main`: `feature/description` or `fix/description`
2. **Code** following existing patterns. No new dependencies without discussion.
3. **Test** — every PR must pass `make test` and add tests for new behavior.
4. **Lint** — run `make lint` and `make typecheck` before pushing.
5. **PR** — open against `main`, describe what and why, reference any issues.

## Good First Issues

Issues tagged [`good first issue`](https://github.com/mtrnix/metronix-memory/labels/good%20first%20issue) are specifically curated for new contributors. They are:

- Scoped to a single file or small module
- Accompanied by a clear expected outcome
- Safe to ship without deep domain knowledge
- A great way to learn the codebase

Look for:
- **Documentation improvements** — fix a typo, add a docstring, improve an error message
- **Test coverage** — add a unit test for an uncovered edge case
- **Small bug fixes** — one-line fixes with clear reproduction steps
- **Connector helpers** — add a utility for an existing connector

## Code Style

- Python 3.12+ only. Use modern syntax (`str | None`, match/case).
- Type hints everywhere. `mypy` strict equivalent.
- `ruff` for linting and formatting. No flake8/pylint/black overrides.
- Docstrings for public APIs. One-liner for simple, Google-style for complex.
- Async-first. All I/O through `await`. No blocking calls in the event loop.
- Log through `structlog`, not `print`.

## Commit Messages

```
area: short description (max 72 chars)

Optional body explaining the why, not the what.
Reference issues: fixes #456
```

Examples: `memory: fix preference injection order`, `connectors: add incremental sync resume`, `docs: add quickstart examples`

## Testing

```bash
make test             # unit suite, -m "not integration" (needs DB services — see above)
make test-all         # unit + integration
```

- Unit tests go in `tests/unit/`; many use the DB services (see [Running checks locally](#running-checks-locally)).
- Integration tests (and anything that needs an external LLM/embeddings) go in `tests/integration/` or are marked `@pytest.mark.integration` so the unit gate skips them.
- New code = new tests. Bug fixes include a regression test.

## Documentation

If your PR changes behavior, update:
- The relevant `.md` in `docs/`
- Inline docstrings for public APIs

## Maintainer repository settings

Maintain branch protection for `main` with pull requests required, at least one
approving review, and required status checks for `ruff (format + lint)` and
`pytest (unit, with services)`. Dismiss stale approvals when new commits are
pushed, require conversations to be resolved before merging, and restrict force
pushes and branch deletion.

## Contributing to Documentation

We welcome documentation contributions, especially new integration guides. All new integration guides must follow a consistent structure.

### Integration Guide Template

Every new integration guide must include these four sections. Use the template below:

```markdown
# [Integration Name]

One-line description of what this integration does.

## Prerequisites

- Metronix Memory running and accessible (`curl http://localhost:8000/health` returns OK)
- [Client-specific prerequisite, e.g., "Claude Desktop installed"]
- `METRONIX_MCP_API_KEY` set in `.env`

## Setup

1. [First step]
2. [Second step]
3. [Add the MCP server configuration]

## Verify

After setup, confirm the connection works:

1. Open a new session in [Client].
2. Call `metronix_status` with `workspace_id="MTRNIX"`.
3. You should receive a status response. If not, check Troubleshooting below.

## Troubleshooting

**Tools not appearing:** Restart [Client] — most clients load MCP servers only at startup.

**Authentication errors:** Confirm the API key in the client config matches `METRONIX_MCP_API_KEY` in `.env`.

**Connection refused:** Verify the stack is running (`curl http://localhost:8000/health`).
```

## DCO

```
Developer Certificate of Origin
Version 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the Apache 2.0 license; or

(b) The contribution is based upon previous work that is covered
    by an appropriate open source license and I have the right
    under that license to submit that work with modifications;
    or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b), or (c) and I have not modified it.
```

Add `Signed-off-by: Your Name <you@example.com>` to your commits.

## Code of Conduct

Be professional. Assume good intent. Feedback is about the code, not the person. If something feels off, open an issue or contact maintainers directly.

## Questions?

Open an [issue](https://github.com/mtrnix/metronix-memory/issues) or comment on your issue. We respond within 1-2 business days.
