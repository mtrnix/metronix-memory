# Test Plan

Test plan for the standalone `hermes-memory-metronix` plugin scaffold.

This plan is split into three layers:

1. fast unit tests for plugin logic
2. integration tests against a live Metronix API
3. manual Hermes end-to-end validation

The goal is not merely “it imports.” The goal is parity with the Hermes
memory-provider lifecycle used by Honcho:

- provider discovery
- config resolution
- prefetch injection before turns
- write-through from `memory(action="add")`
- optional turn sync after turns
- fail-open behavior when Metronix is unavailable

## Scope

In scope:

- `plugin/metronix/__init__.py`
- `plugin/metronix/client.py`
- config file + env var resolution
- REST auth behavior
- workspace scoping
- Hermes-facing memory-provider behavior

Out of scope for this phase:

- custom Hermes setup wizard
- extra Hermes tool schemas
- page/document retrieval beyond memory search
- packaging/publishing automation

## Test Matrix

| Area | Unit | Integration | Manual |
|---|---|---|---|
| Provider discovery shape | yes | no | yes |
| Config precedence | yes | no | yes |
| Bearer auth | yes | yes | yes |
| Login fallback | yes | yes | yes |
| Prefetch formatting | yes | yes | yes |
| Write-through mapping | yes | yes | yes |
| Turn sync | yes | yes | yes |
| Workspace targeting | yes | yes | yes |
| Fail-open behavior | yes | yes | yes |

## Unit Tests

Create these under:

- `standalone/hermes-memory-metronix/tests/unit/`

### 1. Provider contract

File:

- `test_provider_contract.py`

Cases:

- `name == "metronix"`
- `get_tool_schemas()` returns `[]`
- `system_prompt_block()` returns stable text
- `register(ctx)` calls `ctx.register_memory_provider(...)`

### 2. Config resolution

File:

- `test_config_resolution.py`

Cases:

- reads defaults from env when `metronix.json` absent
- `metronix.json` overrides env for non-secret config
- `is_available()` false when base URL missing
- `is_available()` false when workspace missing
- `is_available()` false when both token and email/password missing
- `is_available()` true with bearer token
- `is_available()` true with email/password

### 3. Scope mapping

File:

- `test_scope_mapping.py`

Cases:

- `per_agent -> per_agent`
- `workspace -> global`
- `shared -> global`
- `session -> session`
- unknown scope defaults to `global`

### 4. Kind inference

File:

- `test_kind_inference.py`

Cases:

- `target="user"` maps to `preference`
- default target maps to `fact`
- explicit metadata kind wins when present and valid

### 5. Prefetch filtering and formatting

File:

- `test_prefetch.py`

Cases:

- returns empty string when prefetch disabled
- returns empty string when client missing
- filters search results by configured `prefetch_types`
- includes record ids when `cite_sources=true`
- omits ids when `cite_sources=false`
- wraps injected content in `<memory-context>...</memory-context>`
- returns empty string when all results are empty after filtering
- `queue_prefetch()` populates the per-session cache; `prefetch()` reads it
  without making a network call
- `on_session_switch()` retargets the cached session id and evicts the old
  session's entry

### 6. Client behavior

File:

- `test_client.py`

Cases:

- appends `workspace_id` query parameter
- sends `Authorization: Bearer ...` when token present
- logs in on first request when email/password configured
- caches login token after first successful login
- raises on non-2xx response

### 7. Write-through

File:

- `test_on_memory_write.py`

Cases:

- ignores non-`add` actions
- ignores empty content
- ignores when `write_through=false`
- posts memory record with expected `scope`, `kind`, `source_type`, `tags`
- forwards metadata plus `target`

### 8. Turn sync

File:

- `test_sync_turn.py`

Cases:

- disabled when `sync_turns=false`
- writes user turn as session-scoped memory
- writes assistant turn as session-scoped memory
- skips blank user/assistant content
- uses runtime session id override when passed

### 9. Fail-open behavior

File:

- `test_fail_open.py`

Cases:

- prefetch returns empty on client exception
- `on_memory_write()` swallows client exception
- `sync_turn()` swallows client exception
- warning callback is invoked on failures when present

## Integration Tests

Create these under:

- `standalone/hermes-memory-metronix/tests/integration/`

These tests should be skipped unless:

- `RUN_INTEGRATION_TESTS=1`
- a Metronix API is reachable

Suggested env:

- `METRONIX_BASE_URL`
- `METRONIX_WORKSPACE_ID`
- `METRONIX_AUTH_TOKEN` (REST JWT or personal API key) or `METRONIX_EMAIL` + `METRONIX_PASSWORD`

### 1. Auth smoke

File:

- `test_auth_live.py`

Cases:

- `ping()` succeeds with bearer token
- login fallback returns JWT and reuses it

### 2. Memory write roundtrip

File:

- `test_write_roundtrip.py`

Cases:

- create a fact via client
- verify it appears in `/api/v1/memory/search`
- verify workspace scoping works

### 3. Prefetch roundtrip

File:

- `test_prefetch_roundtrip.py`

Cases:

- insert records of kinds `fact`, `preference`, `pinned`
- search through provider `prefetch()`
- verify formatted block contains expected records
- verify filtered kinds are excluded

### 4. Turn sync roundtrip

File:

- `test_turn_sync_roundtrip.py`

Cases:

- `sync_turn()` creates session-scoped records
- records are discoverable by memory list/search
- session metadata is attached

### 5. Fail-open live

File:

- `test_fail_open_live.py`

Cases:

- invalid token returns auth failure from client
- provider methods do not crash caller on server error

## Manual Hermes End-to-End

### Setup

1. Copy plugin into `~/.hermes/plugins/metronix`.
2. Create `$HERMES_HOME/metronix.json`.
3. Set `memory.provider: metronix` or run `hermes chat --memory-provider metronix`.

### Scenario A: discovery

Expected:

- `hermes memory providers` lists `metronix`
- `hermes memory status` shows `metronix` as selected when configured

### Scenario B: prefetch injection

Steps:

1. Seed a few memory records in the target workspace.
2. Start Hermes chat.
3. Ask a question that should match those memories.

Expected:

- provider activates
- relevant memory is injected before response
- no raw crash or warning on happy path

### Scenario C: write-through from memory tool

Steps:

1. In Hermes, ask it to remember a user preference.
2. Ensure it uses `memory(action="add")`.
3. Query Metronix for that record.

Expected:

- new record appears in Metronix
- kind/scope mapping is correct

### Scenario D: turn sync

Steps:

1. Have a short conversation with clear user/assistant text.
2. Inspect session-scoped memory rows in Metronix.

Expected:

- user and assistant turns are written
- session id metadata is present

### Scenario E: failure handling

Steps:

1. Stop Metronix or break auth.
2. Start Hermes chat with `metronix` provider.

Expected:

- Hermes still answers
- provider degrades quietly or emits warning callback
- no hard startup failure from memory provider path

## Suggested Commands

Unit:

```bash
pytest standalone/hermes-memory-metronix/tests/unit -q
```

Integration:

```bash
RUN_INTEGRATION_TESTS=1 pytest standalone/hermes-memory-metronix/tests/integration -q
```

Manual smoke:

```bash
cp -R standalone/hermes-memory-metronix/plugin/metronix ~/.hermes/plugins/metronix
hermes chat --memory-provider metronix
```

## Exit Criteria

Ready for first real-world dogfood when all are true:

- unit suite passes
- live auth smoke passes
- write-through roundtrip passes
- prefetch roundtrip passes
- manual Hermes discovery works
- manual `memory(action="add")` write-through works
- provider fails open cleanly when Metronix is unavailable

Ready for public release when all are true:

- end-to-end Hermes manual scenarios all pass twice on fresh environments
- install docs are updated
- standalone package extracted or published as its own repo
