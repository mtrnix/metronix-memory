# Inspecting Redis (Docker)

The Metronix Core stack runs Redis in the `metronix-full-redis` container.

| Setting | Value |
|---|---|
| Container | `metronix-full-redis` |
| Image | `redis:7-alpine` |
| Host port | `6380` → container `6379` |
| Auth | none (`requirepass` is empty in this stack) |

Redis is driven through `redis-cli` inside the container. If a password were set,
add `-a "$REDIS_PASSWORD"` (or `--no-auth-warning -a ...`) to each command.

## Inspecting structure

```bash
# Total keys in the default DB (0)
docker exec metronix-full-redis redis-cli DBSIZE

# Per-DB key counts (only DBs with data appear here)
docker exec metronix-full-redis redis-cli INFO keyspace

# Check whether a password is required
docker exec metronix-full-redis redis-cli CONFIG GET requirepass

# Key counts across DBs 0-5
docker exec metronix-full-redis sh -c \
  'for db in 0 1 2 3 4 5; do echo "db$db: $(redis-cli -n $db DBSIZE)"; done'
```

## Reading data

```bash
# List all keys (SCAN is safe on large DBs; KEYS '*' blocks the server)
docker exec metronix-full-redis redis-cli --scan

# Match a pattern
docker exec metronix-full-redis redis-cli --scan --pattern 'cache:*'

# Inspect a key: its type, then read it accordingly
docker exec metronix-full-redis redis-cli TYPE <KEY>
docker exec metronix-full-redis redis-cli GET <KEY>        # string
docker exec metronix-full-redis redis-cli HGETALL <KEY>    # hash
docker exec metronix-full-redis redis-cli LRANGE <KEY> 0 -1 # list
docker exec metronix-full-redis redis-cli SMEMBERS <KEY>   # set
docker exec metronix-full-redis redis-cli TTL <KEY>        # remaining TTL (seconds)
```

## Usage / liveness stats

```bash
docker exec metronix-full-redis redis-cli INFO stats \
  | grep -iE 'keyspace_hits|keyspace_misses|total_commands|expired_keys'
```

## Rendering keys as Markdown

```bash
docker exec metronix-full-redis sh -c '
  printf "| key | type | ttl |\n|---|---|---|\n"
  redis-cli --scan | while read k; do
    printf "| %s | %s | %s |\n" "$k" "$(redis-cli TYPE "$k")" "$(redis-cli TTL "$k")"
  done'
```

Append `> redis_keys.md` to save the table to a file.

## Current state

Redis is **empty** in this stack right now — no keys in any DB:

| metric | value |
|---|---|
| `DBSIZE` (db0) | 0 |
| keyspace (INFO) | empty |
| `total_commands_processed` | 234 |
| `keyspace_hits` / `keyspace_misses` | 0 / 0 |

This is expected: Redis here is used as a transient cache / queue backend. It is
running and healthy, but nothing has populated it yet, so there is no persistent
data to show (unlike Postgres, Qdrant, and Neo4j, which hold the two synced docs).
