#!/usr/bin/env python3
"""Diagnostic: test Cypher syntax patterns against running Memgraph instance.

Run:  cd metronixcore && .venv/bin/python scripts/memgraph_syntax_test.py
"""

import sys

sys.path.insert(0, "src")

from metronix.storage.memgraph import get_memgraph_driver

driver = get_memgraph_driver()

tests = [
    # === Basics ===
    ("RETURN 1", "RETURN 1"),
    ("RETURN 1 AS x", "RETURN 1 AS x"),
    # === Variable naming ===
    ("single-char (e)", "MATCH (e:Entity) RETURN e LIMIT 1"),
    ("multi-char (ent)", "MATCH (ent:Entity) RETURN ent LIMIT 1"),
    ("digit var (e2)", "MATCH (e2:Entity) RETURN e2 LIMIT 1"),
    ("2nd node single (b)", "MATCH (a:Entity)-[r]->(b:Entity) RETURN r LIMIT 1"),
    ("2nd node multi (tgt)", "MATCH (a:Entity)-[r]->(tgt:Entity) RETURN r LIMIT 1"),
    # === Relationship types with labeled nodes ===
    ("[:MENTIONS] no labels", "MATCH (a)-[r:MENTIONS]->(b) RETURN r LIMIT 1"),
    ("[:MENTIONS] with labels", "MATCH (a:Entity)-[r:MENTIONS]->(b:Entity) RETURN r LIMIT 1"),
    ("[:`MENTIONS`] backtick", "MATCH (a:Entity)-[r:`MENTIONS`]->(b:Entity) RETURN r LIMIT 1"),
    ("[:RELATION] with labels", "MATCH (a:Entity)-[r:RELATION]->(b:Entity) RETURN r LIMIT 1"),
    ("[:`RELATION`] backtick", "MATCH (a:Entity)-[r:`RELATION`]->(b:Entity) RETURN r LIMIT 1"),
    ("[:ALIAS] with labels", "MATCH (a:Entity)-[r:ALIAS]->(b:Entity) RETURN r LIMIT 1"),
    ("[:`ALIAS`] backtick", "MATCH (a:Entity)-[r:`ALIAS`]->(b:Entity) RETURN r LIMIT 1"),
    (
        "type(r) filter",
        "MATCH (a:Entity)-[r]->(b:Entity) WHERE type(r) = 'ALIAS' RETURN r LIMIT 1",
    ),
    # === Functions ===
    ("labels(d)", "MATCH (d) WHERE 'Entity' IN labels(d) RETURN d LIMIT 1"),
    ("ANY simple", "MATCH (e:Entity) WHERE ANY(x IN [1,2,3] WHERE x > 1) RETURN e LIMIT 1"),
    # === ACL patterns (the real test) ===
    (
        "ANY g IN prop",
        "MATCH (d) WHERE 'Document' IN labels(d) "
        "AND ANY(g IN d.access_groups WHERE g IN ['test']) RETURN d LIMIT 1",
    ),
    (
        "access_groups IS NULL",
        "MATCH (d) WHERE 'Document' IN labels(d) AND d.access_groups IS NULL RETURN d LIMIT 1",
    ),
    (
        "ACL full OR",
        "MATCH (d) WHERE 'Document' IN labels(d) "
        "AND (d.access_groups IS NULL OR ANY(g IN d.access_groups WHERE g IN ['test'])) "
        "RETURN d LIMIT 1",
    ),
    (
        "ACL in MATCH chain",
        "MATCH (e:Entity)<-[:MENTIONS]-(d) "
        "WHERE e.workspace_id = 'MTRNIX' "
        "AND ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
        "AND d.doc_label IS NOT NULL "
        "AND (d.access_groups IS NULL OR ANY(g IN d.access_groups WHERE g IN ['test'])) "
        "RETURN d LIMIT 1",
    ),
    (
        "ACL multi-group",
        "MATCH (e:Entity)<-[:MENTIONS]-(d) "
        "WHERE e.workspace_id = 'MTRNIX' "
        "AND ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
        "AND d.doc_label IS NOT NULL "
        "AND (d.workspace_id = 'MTRNIX' OR d.workspace_id IS NULL) "
        "AND (d.access_groups IS NULL OR ANY(g IN d.access_groups WHERE g IN ['grp1', 'grp2'])) "
        "RETURN d",
    ),
    # === Backtick-escaped property names ===
    (
        "d.`access_groups` IS NULL",
        "MATCH (d) WHERE 'Document' IN labels(d) AND d.`access_groups` IS NULL RETURN d LIMIT 1",
    ),
    (
        "ACL backtick prop",
        "MATCH (e:Entity)<-[:MENTIONS]-(d) "
        "WHERE e.workspace_id = 'MTRNIX' "
        "AND ('Document' IN labels(d) OR 'JiraIssue' IN labels(d)) "
        "AND d.doc_label IS NOT NULL "
        "AND (d.`access_groups` IS NULL OR ANY(g IN d.`access_groups` WHERE g IN ['test'])) "
        "RETURN d LIMIT 1",
    ),
    # === UNION ===
    (
        "UNION same col",
        "MATCH (a:Entity) RETURN a LIMIT 1 UNION MATCH (a:Entity) RETURN a LIMIT 1",
    ),
    # === Undirected ===
    ("undirected untyped", "MATCH (a:Entity)-[r]-(b:Entity) RETURN r LIMIT 1"),
    ("undirected typed", "MATCH (a:Entity)-[r:RELATION]-(b:Entity) RETURN r LIMIT 1"),
]

print("=== Memgraph syntax diagnostic ===\n")
for label, query in tests:
    try:
        with driver.session() as s:
            result = list(s.run(query))
            print(f"  OK   {label:35s} ({len(result)} rows)")
    except Exception as e:
        msg = str(e)
        if "{message:" in msg:
            msg = msg.split("{message:")[-1].strip().rstrip("}'\"")
        print(f"  FAIL {label:35s} {msg}")

driver.close()
