---
name: memgraph-compat
description: Memgraph 2.18.1 + neo4j driver 5.28 Cypher parser compatibility constraints
type: reference
---

## Memgraph 2.18.1 + neo4j driver 5.28 parser quirks

Discovered via diagnostic script (`scripts/memgraph_syntax_test.py`).

### Rules

1. **No digits in Cypher variable names** — `e2`, `d1` fail everywhere. Use `a`, `b`, `n`, `m` etc.
2. **Single-char variables after relationship patterns** — `(a)-[r]->(tgt)` fails, `(a)-[r]->(b)` works.
3. **Property names starting with keyword-prefix letters** need backtick-escaping:
   - `d.access_groups` fails (`a` prefix collides with `AS`, `AND`, `ALL`, `ANY`)
   - `d.workspace_id` works (`w` doesn't collide at 2nd char)
   - Fix: `` d.`access_groups` ``
4. **Relationship type names that share keyword prefixes** need backtick-escaping:
   - `[:ALIAS]` fails (prefix `AL` → keyword `ALL`)
   - `[:RELATION]` fails (prefix `RE` → keyword `RETURN`, `REGISTER`)
   - `[:MENTIONS]` works (no keyword collision)
5. **Safe alternative**: use `type(r) = 'TYPENAME'` in WHERE clause instead of `[:TYPENAME]` in pattern.
6. **`labels(n)` function works** — use `'Label' IN labels(n)` instead of `n:Label` in WHERE after AND.
7. **UNION requires matching column names** — both sides must RETURN same alias.

### Workarounds applied in graph_ops.py

- All second-node variables: single-char (`b`, `m`, `n`)
- ALIAS relationship: `MATCH (e)-[r]->(n) WHERE type(r) = 'ALIAS'`
- Document label checks: `'Document' IN labels(d)` instead of `d:Document`
- Property access: `` d.`access_groups` `` (backtick-escaped)
