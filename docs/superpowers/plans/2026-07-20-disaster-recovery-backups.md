# Disaster Recovery Backups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide verified full-system backup and isolated restore scripts for PostgreSQL, Qdrant, Neo4j, Redis, and snapshot artifacts.

**Tracking:** GitHub #349. This is disaster recovery and deliberately independent of the Time Machine product work in #348.

**Architecture:** Shell orchestration calls vendor-supported backup primitives and writes an immutable manifest with SHA-256 checksums. PostgreSQL is authoritative; Qdrant and Neo4j artifacts reduce recovery time; Redis is optional because it stores temporary sessions and queues. Restore is always directed at an explicitly named isolated target.

**Tech Stack:** POSIX shell, Docker Compose, pg_dump/pg_restore, Qdrant HTTP API, Neo4j admin commands, Redis CLI, pytest shell tests.

## Global Constraints

- Backups are not Time-Machine snapshots.
- Do not include secrets by default.
- Never restore in place; require an explicit isolated target name.
- Fail on a missing required component; Redis is optional and recorded as absent.
- Verify every file checksum before restore.

---

### Task 1: Add manifest library and deterministic component discovery

**Files:**
- Create: `scripts/backup/lib.sh`
- Create: `scripts/backup/manifest.py`
- Create: `tests/installer/test_backup_manifest.sh`
- Modify: `docs/operations/backups.md`

**Interfaces:**
- Produces `metronix-backup-manifest.json` and `verify_manifest <dir>`.

- [ ] **Step 1: Write the failing manifest test**

```sh
run scripts/backup/manifest.py create "$TMPDIR/bundle" "$TMPDIR/manifest.json"
assert_json_field "$TMPDIR/manifest.json" '.format_version' '1'
run scripts/backup/manifest.py verify "$TMPDIR/manifest.json" "$TMPDIR/bundle"
```

- [ ] **Step 2: Run test to verify failure**

Run: `bash tests/installer/test_backup_manifest.sh`

Expected: FAIL because the manifest utility does not exist.

- [ ] **Step 3: Implement manifest handling**

```python
def build_manifest(root: Path, components: list[Component]) -> dict[str, object]:
    return {"format_version": 1, "created_at": datetime.now(UTC).isoformat(), "components": [c.to_dict() for c in components]}
```

The manifest must include component name, relative path, SHA-256, byte count, command version, required flag, and restore status. Reject absolute paths and `..` members.

- [ ] **Step 4: Run manifest test**

Run: `bash tests/installer/test_backup_manifest.sh`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backup/lib.sh scripts/backup/manifest.py tests/installer/test_backup_manifest.sh docs/operations/backups.md
git commit -m "feat: add backup manifest verification"
```

### Task 2: Implement create and verify commands

**Files:**
- Create: `scripts/metronix-backup`
- Create: `scripts/backup/create-postgres.sh`
- Create: `scripts/backup/create-qdrant.sh`
- Create: `scripts/backup/create-neo4j.sh`
- Create: `scripts/backup/create-redis.sh`
- Test: `tests/installer/test_backup_create.sh`

**Interfaces:**
- Produces `scripts/metronix-backup create --output <empty-dir>` and `verify --bundle <dir>`.

- [ ] **Step 1: Write failing mocked-component test**

```sh
run scripts/metronix-backup create --output "$TMPDIR/bundle"
assert_file_exists "$TMPDIR/bundle/manifest.json"
assert_file_exists "$TMPDIR/bundle/postgres.sql.gz"
assert_json_field "$TMPDIR/bundle/manifest.json" '.components[] | select(.name=="redis") | .status' 'optional_absent'
```

- [ ] **Step 2: Run test to verify failure**

Run: `bash tests/installer/test_backup_create.sh`

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Implement component commands**

```sh
case "$1" in
  create) require_empty_dir "$output"; create_postgres "$output"; create_qdrant "$output"; create_neo4j "$output"; create_redis_optional "$output"; python scripts/backup/manifest.py create "$output" "$output/manifest.json" ;;
  verify) python scripts/backup/manifest.py verify "$bundle/manifest.json" "$bundle" ;;
esac
```

Use `pg_dump --format=custom`, Qdrant collection snapshot endpoints, a documented Neo4j offline/online command selected from compose configuration, and `redis-cli --rdb` only when Redis persistence is enabled. Capture command failures, never fabricate an artifact.

- [ ] **Step 4: Run create/verify tests**

Run: `bash tests/installer/test_backup_create.sh && bash tests/installer/test_backup_manifest.sh`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/metronix-backup scripts/backup/create-postgres.sh scripts/backup/create-qdrant.sh scripts/backup/create-neo4j.sh scripts/backup/create-redis.sh tests/installer/test_backup_create.sh
git commit -m "feat: create verified system backups"
```

### Task 3: Implement isolated restore and recovery drill

**Files:**
- Create: `scripts/backup/restore.sh`
- Create: `tests/installer/test_backup_restore.sh`
- Modify: `docs/operations/backups.md`

- [ ] **Step 1: Write failing restore-safety test**

```sh
run scripts/metronix-backup restore --bundle "$TMPDIR/bundle" --into "recovery-test"
assert_output --partial 'refusing in-place restore'
run scripts/metronix-backup restore --bundle "$TMPDIR/bundle" --into "recovery-test" --confirm-isolated-target
assert_file_exists "$TMPDIR/restore-report.json"
```

- [ ] **Step 2: Run test to verify failure**

Run: `bash tests/installer/test_backup_restore.sh`

Expected: FAIL because restore does not exist.

- [ ] **Step 3: Implement restore**

```sh
verify_bundle "$bundle" || exit 1
require_isolated_target "$target" || exit 2
restore_postgres "$bundle" "$target"
restore_qdrant "$bundle" "$target"
restore_neo4j "$bundle" "$target"
run_health_and_count_checks "$target"
```

Require `--confirm-isolated-target`, record component-level results in `restore-report.json`, and print a separate manual cutover instruction. Do not implement automatic production cutover.

- [ ] **Step 4: Run recovery tests**

Run: `bash tests/installer/test_backup_restore.sh`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backup/restore.sh tests/installer/test_backup_restore.sh docs/operations/backups.md
git commit -m "feat: restore backups into isolated targets"
```
