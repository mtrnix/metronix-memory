# Agent Memory Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export and import durable compacted agent memory through a versioned, safe, portable Agent Memory Bundle (`.amb`).

**Tracking:** GitHub #347. Depends on GitHub #343 and #344.

**Architecture:** The bundle is a gzip/zip archive with JSON/JSONL files and checksums. Export reads only durable records, ledgers, profiles, relationships, and tombstones; import validates all members, defaults to per-agent scope, and uses candidate status for incomplete provenance.

**Tech Stack:** Python standard library archive/json/hashlib, FastAPI, SQLAlchemy async, pytest.

## Global Constraints

- Do not export expired raw event text.
- Preserve tombstones and never overwrite live memory without explicit merge mode.
- Bundle schema is versioned from its first release.
- Import validates paths, checksums, workspace authorization, and maximum file sizes.

---

### Task 1: Define bundle schema and archive codec

**Files:**
- Create: `src/metronix/memory/bundle.py`
- Create: `src/metronix/memory/bundle_models.py`
- Test: `tests/unit/memory/test_bundle.py`

**Interfaces:**
- Produces `AgentMemoryBundleWriter.write()`, `AgentMemoryBundleReader.read()`, and `BundleManifest`.

- [ ] **Step 1: Write failing round-trip and traversal tests**

```python
def test_bundle_round_trip_and_checksum(tmp_path):
    path = AgentMemoryBundleWriter(tmp_path).write(bundle_fixture())
    assert AgentMemoryBundleReader().read(path).manifest.format_version == 1

def test_reader_rejects_traversal_member(tmp_path):
    assert_raises(BundleValidationError, AgentMemoryBundleReader().read, malicious_bundle(tmp_path, "../x"))
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run --extra dev pytest tests/unit/memory/test_bundle.py -q`

Expected: FAIL because the bundle codec does not exist.

- [ ] **Step 3: Implement codec**

```python
REQUIRED_MEMBERS = {"manifest.json", "profiles.json", "memories.jsonl", "session_summaries.jsonl", "commitments.jsonl", "relationships.jsonl", "tombstones.jsonl", "checksums.sha256"}

class BundleManifest(BaseModel):
    format_version: Literal[1] = 1
    workspace_id: str
    agent_id: str
    generated_at: datetime
```

Use safe fixed archive member names, UTF-8 JSONL, SHA-256 of each plaintext member, and a byte cap before parsing. Do not include `conversation_events` in the writer.

- [ ] **Step 4: Run codec tests**

Run: `uv run --extra dev pytest tests/unit/memory/test_bundle.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/memory/bundle.py src/metronix/memory/bundle_models.py tests/unit/memory/test_bundle.py
git commit -m "feat: add agent memory bundle codec"
```

### Task 2: Implement export/import service and Markdown renderer

**Files:**
- Create: `src/metronix/memory/bundle_service.py`
- Modify: `src/metronix/export/render.py`
- Modify: `src/metronix/storage/memory_postgres.py`
- Test: `tests/integration/memory/test_bundle_roundtrip.py`

**Interfaces:**
- Produces `AgentMemoryBundleService.export_agent()` and `import_agent(..., merge: Literal["reject", "append"])`.

- [ ] **Step 1: Write failing safe-import tests**

```python
async def test_import_defaults_to_private_candidate_and_preserves_tombstone(service):
    result = await service.import_agent(bundle_without_provenance(), target_agent_id="new-agent", merge="append")
    assert result.created[0].scope is MemoryScope.PER_AGENT
    assert result.created[0].status is LifecycleStatus.CANDIDATE
    assert result.tombstones_applied == 1
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest tests/integration/memory/test_bundle_roundtrip.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement service and renderer**

```python
async def import_agent(self, bundle: Path, *, target_agent_id: str, merge: str) -> BundleImportResult:
    parsed = self._reader.read(bundle)
    self._reject_conflicts(parsed, target_agent_id, merge)
    return await self._store_import(parsed, target_agent_id, default_scope=MemoryScope.PER_AGENT)
```

Render durable records and ledgers to `MEMORY.md` without source event text. Persist tombstones in a dedicated table created by a migration, and apply them before imported active records.

- [ ] **Step 4: Run round-trip tests**

Run: `uv run --extra dev pytest tests/integration/memory/test_bundle_roundtrip.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/memory/bundle_service.py src/metronix/export/render.py src/metronix/storage/memory_postgres.py migrations/versions/030_memory_tombstones.py tests/integration/memory/test_bundle_roundtrip.py
git commit -m "feat: import and export agent memory bundles"
```

### Task 3: Expose authenticated bundle endpoints and generic adapters

**Files:**
- Create: `src/metronix/api/routes/memory_bundles.py`
- Modify: `src/metronix/api/app.py`
- Create: `docs/guides/agent-memory-bundles.md`
- Test: `tests/integration/api/test_memory_bundles.py`

- [ ] **Step 1: Write failing authorization test**

```python
async def test_bundle_import_cannot_target_foreign_workspace(client, bundle):
    response = await client.post("/api/v1/memory-bundles/import?workspace_id=foreign", files={"bundle": bundle})
    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest tests/integration/api/test_memory_bundles.py -q`

Expected: FAIL with a missing route.

- [ ] **Step 3: Implement endpoints and documentation**

```python
@router.post("/export/{agent_id}")
async def export_bundle(agent_id: str, ...): ...

@router.post("/import")
async def import_bundle(agent_id: str, merge: Literal["reject", "append"] = "reject", ...): ...
```

Require editor access for imports, viewer access for exports, and workspace-scoped agent validation. Document generic JSONL, Markdown, and future Codex/Claude/Hermes adapters.

- [ ] **Step 4: Run endpoint tests**

Run: `uv run --extra dev pytest tests/integration/api/test_memory_bundles.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/api/routes/memory_bundles.py src/metronix/api/app.py docs/guides/agent-memory-bundles.md tests/integration/api/test_memory_bundles.py
git commit -m "feat: expose portable agent memory bundles"
```
