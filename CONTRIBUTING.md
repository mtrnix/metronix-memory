# Contributing to Metronix Memory

Thanks for wanting to help. Metronix Memory is an open-core AI memory + knowledge infrastructure. We welcome contributions.

## Getting Started

1. **Fork** the repo and clone your fork.
2. **Read** [`docs/reference/architecture.md`](docs/reference/architecture.md) for
   architecture, conventions, and layer rules.
3. **Run tests** before touching anything:
   ```bash
   make docker-up   # start databases
   make test        # unit tests (no live services needed)
   make lint        # ruff check + format
   make typecheck   # mypy
   ```

## Architecture Constraint

Metronix Memory has a **strict 6-layer one-way dependency architecture** (L0 to L6). You
cannot import upward. See [`docs/reference/architecture.md`](docs/reference/architecture.md)
for the layer map.

Before adding any import, verify the layer belongs below your target.

## Workflow

```
Fork → Branch → Code → Test → Lint → PR
```

1. **Branch** from `develop`: `feature/description` or `fix/description`
2. **Code** following existing patterns. No new dependencies without discussion.
3. **Test** — every PR must pass `make test` and add tests for new behavior.
4. **Lint** — run `make lint` and `make typecheck` before pushing.
5. **PR** — open against `develop`, describe what and why, reference any issues.

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
make test             # unit tests (fast, no services)
make test-all         # unit + integration (needs docker-up)
```

- Unit tests go in `tests/unit/`. No live DB connections.
- Integration tests go in `tests/integration/`. Mark with `@pytest.mark.integration`.
- New code = new tests. Bug fixes include a regression test.

## Documentation

If your PR changes behavior, update:
- The relevant `.md` in `docs/`
- [`docs/reference/architecture.md`](docs/reference/architecture.md) if architecture changes
- [`docs/reference/configuration.md`](docs/reference/configuration.md) if configuration changes
- Inline docstrings for public APIs

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

Open a [discussion](https://github.com/mtrnix/metronix-memory/discussions) or comment on your issue. We respond within 1-2 business days.
