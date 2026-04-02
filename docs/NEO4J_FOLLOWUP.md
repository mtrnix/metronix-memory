# Neo4j Migration — Follow-up Tasks

Post-migration improvements that are out of scope for the initial swap.

## 1. Rename single-character Cypher variables

**Scope:** `storage/graph_ops.py` (~200 occurrences)

**Why:** Memgraph 2.18.1 required single-char variables after relationship patterns
(`(e)-[r]->(b)` instead of `(entity)-[rel]->(target)`). Neo4j has no such restriction.

**Impact:** Readability only, no functional change.

## 2. Async Neo4j driver

**Scope:** All files using `get_graph_driver()` and `driver.session()`

**Why:** Currently sync, wrapped with `asyncio.to_thread()` from API layer.
Neo4j Python driver supports `AsyncGraphDatabase` natively.

**Impact:** Performance improvement for concurrent graph operations.

## 3. Neo4j indexes

**Scope:** `ensure_graph_indexes()` in `storage/neo4j_graph.py` (already migrated to Neo4j syntax)

**Why:** Current indexes are basic single-property. For production scale, consider:
- Composite index: `CREATE INDEX FOR (e:Entity) ON (e.name, e.workspace_id)`
- Full-text index for entity name search

**Impact:** Query performance under load.

## 4. Orphan node detection

**Scope:** `storage/dashboard_queries.py:get_graph_stats_data()`

**Why:** Was skipped in Memgraph 2.18.1 ("not compatible"). Neo4j supports it.

**Query:** `MATCH (n) WHERE NOT (n)--() AND n.workspace_id = $ws RETURN n LIMIT 100`

**Impact:** Dashboard completeness.

## 5. Implement health check

**Scope:** `observability/health.py:_check_neo4j()`

**Why:** Currently a stub returning "unchecked". Should verify bolt:// connectivity
with an actual `RETURN 1` query via `AsyncGraphDatabase`.

**Impact:** Accurate readiness reporting.
