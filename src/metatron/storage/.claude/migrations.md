
# Database Migrations

## Auto-migration on Startup
Migrations run automatically in `api/app.py` → `lifespan()` via `run_migrations_sync()`.

No need for manual `alembic upgrade head` — but `make migrate` still works for explicit runs.

## How It Works
1. `lifespan()` calls `asyncio.to_thread(run_migrations_sync, sync_dsn, async_dsn)`
2. `run_migrations_sync()` acquires PostgreSQL advisory lock (prevents race condition with multiple replicas)
3. Runs `alembic upgrade head` programmatically
4. Releases lock
5. If migration fails — logs error, app continues startup (schema may already be up to date)

## Advisory Lock
- Lock ID: stable 63-bit hash from `md5("metatron_migrations")`
- Uses `pg_try_advisory_lock()` → if fails, `pg_advisory_lock()` (blocking wait)
- After lock acquired: check if already at head, skip if so

## Adding New Migrations
```bash
make migrate-new name="description"
# or
alembic revision --autogenerate -m "description"
```
Migrations are in `migrations/versions/`. They will auto-apply on next startup.

## Two DSNs
- Sync DSN (psycopg2) — used for advisory lock only
- Async DSN (asyncpg) — passed to alembic config (env.py requires it)
