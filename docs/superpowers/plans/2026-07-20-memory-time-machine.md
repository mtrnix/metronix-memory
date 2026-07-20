# Memory Time Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn existing per-agent snapshots into a retained, scheduled, reversible Time-Machine history with preview and fork operations.

**Architecture:** Existing JSONL+gzip snapshot files remain compatible full bases. A PostgreSQL index identifies base/delta checkpoints and retention state; deltas are content-addressed operations reconstructed against a base. Restores always create a pre-restore checkpoint and may target a new agent instead of replacing the current one.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, FastAPI, pytest.

## Global Constraints

- Time Machine operates on compacted durable records, not raw conversation events.
- Never delete the final valid restore point for an agent.
- Restore is workspace and agent scoped, checksum verified, and reversible.
- Full snapshot fallback is required when a delta chain is missing or invalid.

---

### Task 1: Add Time-Machine checkpoint index and delta codec

**Files:**
- Create: `migrations/versions/031_time_machine_checkpoints.py`
- Create: `src/metronix/memory/time_machine.py`
- Modify: `src/metronix/memory/snapshot.py`
- Test: `tests/unit/memory/test_time_machine.py`

**Interfaces:**
- Produces `TimeMachineService.create_checkpoint()`, `list_checkpoints()`, and `reconstruct()`.

- [ ] **Step 1: Write failing delta reconstruction tests**

```python
async def test_reconstruct_applies_delta_to_base(service):
    base = await service.create_checkpoint("agent-a", kind="base")
    await mutate_memory("agent-a", content="new preference")
    delta = await service.create_checkpoint("agent-a", kind="delta")
    records = await service.reconstruct(delta.id)
    assert {r.content for r in records} >= {"new preference"}
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest tests/unit/memory/test_time_machine.py -q`

Expected: FAIL because `TimeMachineService` does not exist.

- [ ] **Step 3: Implement checkpoint index and codec**

```python
@dataclass(frozen=True)
class TimeMachineCheckpoint:
    id: str; workspace_id: str; agent_id: str; base_snapshot_id: str | None
    kind: Literal["base", "delta"]; content_hash: str; created_at: datetime
```

Create `time_machine_checkpoints` with `(workspace_id, agent_id, created_at DESC)` index. Compute a deterministic delta as `upsert` full record JSON plus `delete` record ids; persist its SHA-256 and base id. Reconstruct by verified base read plus ordered verified deltas.

- [ ] **Step 4: Run unit tests**

Run: `uv run --extra dev pytest tests/unit/memory/test_time_machine.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/031_time_machine_checkpoints.py src/metronix/memory/time_machine.py src/metronix/memory/snapshot.py tests/unit/memory/test_time_machine.py
git commit -m "feat: add memory Time Machine checkpoints"
```

### Task 2: Schedule retention and pre-destructive checkpoints

**Files:**
- Create: `src/metronix/memory/time_machine_worker.py`
- Modify: `src/metronix/core/config.py`
- Modify: `src/metronix/memory/service.py`
- Modify: `src/metronix/memory/snapshot.py`
- Test: `tests/unit/memory/test_time_machine_worker.py`
- Test: `tests/integration/memory/test_time_machine_retention.py`

**Interfaces:**
- Produces `TimeMachineWorker.run_once()` and `TimeMachineService.prune()`.

- [ ] **Step 1: Write failing retention and safety tests**

```python
async def test_retention_keeps_last_checkpoint_and_protected_pre_restore(service):
    await seed_hourly_checkpoints(service, count=30)
    deleted = await service.prune("agent-a", now=fixed_now())
    assert deleted > 0
    assert await service.list_checkpoints("agent-a")
    assert any(c.trigger == "pre_restore" for c in await service.list_checkpoints("agent-a"))
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run --extra dev pytest tests/unit/memory/test_time_machine_worker.py tests/integration/memory/test_time_machine_retention.py -q`

Expected: FAIL because scheduling and retention do not exist.

- [ ] **Step 3: Implement scheduled checkpoints and retention**

```python
class RetentionPolicy(BaseModel):
    hourly: int = 24
    daily: int = 30
    weekly: int = 12
    monthly: int = 12
```

Add flags and cadence settings. Subscribe to destructive memory events and create `pre_delete`, `pre_reset`, and `pre_restore` checkpoints synchronously before mutation; scheduled checkpoints are best-effort but logged. Prune only checkpoints outside all retention buckets and never prune a referenced base or the newest valid checkpoint.

- [ ] **Step 4: Run retention tests**

Run: `uv run --extra dev pytest tests/unit/memory/test_time_machine_worker.py tests/integration/memory/test_time_machine_retention.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/memory/time_machine_worker.py src/metronix/core/config.py src/metronix/memory/service.py src/metronix/memory/snapshot.py tests/unit/memory/test_time_machine_worker.py tests/integration/memory/test_time_machine_retention.py
git commit -m "feat: retain scheduled memory checkpoints"
```

### Task 3: Add timeline, preview, fork, and restore API

**Files:**
- Create: `src/metronix/api/routes/time_machine.py`
- Modify: `src/metronix/api/app.py`
- Test: `tests/integration/api/test_time_machine.py`
- Modify: `docs/API.md`

- [ ] **Step 1: Write failing API tests**

```python
async def test_preview_and_fork_do_not_replace_live_agent(client):
    preview = await client.get(f"/api/v1/time-machine/{checkpoint_id}/preview")
    assert preview.status_code == 200
    fork = await client.post(f"/api/v1/time-machine/{checkpoint_id}/fork", json={"agent_id": "agent-copy"})
    assert fork.status_code == 201
    assert await live_memory("agent-a") == original_memory
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest tests/integration/api/test_time_machine.py -q`

Expected: FAIL with a missing route.

- [ ] **Step 3: Implement scoped API**

```python
@router.get("/{checkpoint_id}/preview")
async def preview_checkpoint(checkpoint_id: str, ...): ...

@router.post("/{checkpoint_id}/fork", status_code=201)
async def fork_checkpoint(checkpoint_id: str, body: ForkRequest, ...): ...
```

Require viewer for timeline/preview and editor for fork/restore. Verify checkpoint workspace ownership, create `pre_restore` before replace, and return restored/forked record counts and checkpoint ids.

- [ ] **Step 4: Run API and existing snapshot tests**

Run: `uv run --extra dev pytest tests/integration/api/test_time_machine.py tests/unit/memory/test_snapshot_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/api/routes/time_machine.py src/metronix/api/app.py docs/API.md tests/integration/api/test_time_machine.py
git commit -m "feat: expose memory Time Machine history"
```
