# Task 1 persistence-boundary hardening report

## Scope

Hardened only `ConversationPostgresStore.append_event()` before it opens a
database transaction. Retention policy defaults, `forever` null-expiry
behavior, and ledger provenance persistence are unchanged.

## Safety policy

The deterministic, local gate rejects raw events containing:

- explicitly labelled or known-provider credential material;
- unlabelled token-like strings of at least 24 credential characters when they
  use at least two character classes and have Shannon entropy of at least 3.5
  bits per character;
- priority/precedence attempts directed at protected system, developer,
  operating, policy, safety, or instruction text;
- role escalation into system, developer, root, or administrator authority;
- protected-instruction disclosure attempts and instruction-shaped system or
  developer headers.

The gate raises `UnsafeConversationContentError` before `engine.begin()` and
never calls an external model. Ordinary prose, ordinary references to system
rules, password-reset requests, and non-instruction log headers remain
persistable.

## Test coverage

- Bypass-oriented integration tests prove that high-entropy token strings,
  priority-over-operating-rules phrasing, role escalation, and system-header
  instructions are rejected without persistence.
- A focused unit test proves bypass content is rejected before a database
  connection is opened.
- Integration coverage now parameterizes all public retention policies:
  `24h`, `7d`, `30d`, and `forever`.
- Existing provenance coverage confirms event expiry does not delete the
  session ledger.
- Test cleanup now removes successful ordinary-content rows; expiry assertions
  identify the generated session so repeated integration runs are stable even
  though expiry is intentionally global.

## Verification

Run against local PostgreSQL on port 5433:

```text
POSTGRES_PORT=5433 uv run --extra dev pytest tests/integration/memory/test_conversation_postgres.py -q
16 passed in 1.90s

uv run --extra dev pytest tests/unit/storage/test_conversation_postgres_safety.py -q
3 passed in 0.80s

uv run --extra dev ruff check src/metronix/storage/conversation_postgres.py tests/unit/storage/test_conversation_postgres_safety.py tests/integration/memory/test_conversation_postgres.py
All checks passed!

uv run --extra dev ruff format --check src/metronix/storage/conversation_postgres.py tests/unit/storage/test_conversation_postgres_safety.py tests/integration/memory/test_conversation_postgres.py
3 files already formatted

uv run --extra dev mypy src/metronix/storage/conversation_postgres.py
Success: no issues found in 1 source file
```

## Concern

High-entropy detection is deliberately conservative for raw-event retention:
some technical identifiers or opaque values may be rejected. This is a
fail-closed privacy tradeoff, while ordinary conversational prose and ordinary
mentions of sensitive concepts are accepted. It is not a substitute for
secrets-management controls at event ingestion.
