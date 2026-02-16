"""Memgraph knowledge graph audit — detect duplicates, orphans, quality issues.

Usage:
    python -m metatron.scripts.graph_audit
"""

from __future__ import annotations

import sys
from collections import defaultdict

from metatron.storage.memgraph import get_memgraph_driver


def _run(session, query: str) -> list[dict]:
    """Run a Cypher query and return results as list of dicts."""
    result = session.run(query)
    return [dict(record) for record in result]


def _header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def _subheader(title: str) -> None:
    print(f"\n--- {title} ---")


def audit() -> None:
    """Run all diagnostic queries and print results."""
    issues: dict[str, list[str]] = {
        "CRITICAL": [],
        "WARNING": [],
        "INFO": [],
    }

    driver = get_memgraph_driver()

    with driver.session() as s:
        # ---------------------------------------------------------------
        # 1. Basic stats
        # ---------------------------------------------------------------
        _header("1. BASIC STATS")

        _subheader("Node counts by label")
        rows = _run(s, "MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC;")
        total_nodes = 0
        for r in rows:
            print(f"  {r['type']:20s}  {r['count']:>6}")
            total_nodes += r["count"]
        print(f"  {'TOTAL':20s}  {total_nodes:>6}")

        _subheader("Relationship counts by type")
        rows = _run(s, "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC;")
        total_rels = 0
        for r in rows:
            print(f"  {r['rel_type']:20s}  {r['count']:>6}")
            total_rels += r["count"]
        print(f"  {'TOTAL':20s}  {total_rels:>6}")
        issues["INFO"].append(f"Graph has {total_nodes} nodes and {total_rels} relationships")

        # ---------------------------------------------------------------
        # 1b. Entity type distribution
        # ---------------------------------------------------------------
        _subheader("Entity types")
        rows = _run(s, (
            "MATCH (e:Entity) "
            "RETURN e.type AS type, count(e) AS count "
            "ORDER BY count DESC;"
        ))
        person_types: list[str] = []
        for r in rows:
            etype = r["type"] or "(null)"
            print(f"  {etype:30s}  {r['count']:>4}")
            # Detect person-like types (English and Russian)
            low = etype.lower()
            if any(kw in low for kw in ("person", "персон", "человек", "member",
                                         "developer", "разработч", "team member",
                                         "сотрудник", "user", "участник")):
                person_types.append(etype)

        if person_types:
            issues["INFO"].append(f"Person-like entity types: {person_types}")
        else:
            issues["INFO"].append("No person-like entity types detected — checking all entities for name duplicates")

        # ---------------------------------------------------------------
        # 2. Duplicate entity detection (persons)
        # ---------------------------------------------------------------
        _header("2. DUPLICATE ENTITY DETECTION (Persons)")

        # Build type filter: use detected person types, or fall back to all
        if person_types:
            type_list = ", ".join(f"'{t}'" for t in person_types)
            person_query = (
                f"MATCH (e:Entity) WHERE e.type IN [{type_list}] "
                "OPTIONAL MATCH (e)<-[m:MENTIONS]-() "
                "WITH e, count(m) AS mentions "
                "RETURN e.name AS name, e.workspace_id AS ws, e.type AS type, mentions "
                "ORDER BY e.name;"
            )
        else:
            # No person types found — check ALL entities for duplicates
            person_query = (
                "MATCH (e:Entity) "
                "OPTIONAL MATCH (e)<-[m:MENTIONS]-() "
                "WITH e, count(m) AS mentions "
                "RETURN e.name AS name, e.workspace_id AS ws, e.type AS type, mentions "
                "ORDER BY e.name;"
            )

        rows = _run(s, person_query)

        if not rows:
            print("  No entities found.")
        else:
            label = "person" if person_types else "all"
            print(f"  Scanning {len(rows)} entities (scope: {label}):\n")
            if person_types:
                for r in rows:
                    print(f"  {r['name']:40s}  type={r['type']}  ws={r['ws']}  mentions={r['mentions']}")

            # Detect potential duplicates: normalize names and group
            normalized: dict[str, list[str]] = defaultdict(list)
            for r in rows:
                name = r["name"]
                # Normalize: lowercase, replace _ and . with space, strip
                key = name.lower().replace("_", " ").replace(".", " ").strip()
                # Also try removing middle parts for "first last" matching
                normalized[key].append(name)

            _subheader("Potential duplicates (same normalized name)")
            dup_count = 0
            for key, names in sorted(normalized.items()):
                if len(names) > 1:
                    dup_count += 1
                    print(f"  '{key}' -> {names}")
                    issues["CRITICAL"].append(
                        f"Duplicate person entities: {names} (same normalized name '{key}')"
                    )

            if dup_count == 0:
                print("  No exact-normalized duplicates found.")

            # Check for Cyrillic vs Latin variants
            _subheader("Cyrillic vs Latin name variants")
            cyrillic_names = [r["name"] for r in rows if any("\u0400" <= c <= "\u04ff" for c in r["name"])]
            latin_names = [r["name"] for r in rows if all(c < "\u0400" or c > "\u04ff" for c in r["name"] if c.isalpha())]
            if cyrillic_names and latin_names:
                print(f"  Cyrillic names ({len(cyrillic_names)}): {cyrillic_names[:10]}")
                print(f"  Latin names ({len(latin_names)}): {latin_names[:10]}")
                issues["WARNING"].append(
                    f"Mixed Cyrillic ({len(cyrillic_names)}) and Latin ({len(latin_names)}) person names — may contain cross-script duplicates"
                )
            elif cyrillic_names:
                print(f"  All {len(cyrillic_names)} names are Cyrillic.")
            elif latin_names:
                print(f"  All {len(latin_names)} names are Latin.")
            else:
                print("  No person names to compare.")

        # ---------------------------------------------------------------
        # 3. Orphaned entities
        # ---------------------------------------------------------------
        _header("3. ORPHANED ENTITIES (no relationships at all)")

        rows = _run(s, (
            "MATCH (e:Entity) "
            "OPTIONAL MATCH (e)<-[m:MENTIONS]-() "
            "OPTIONAL MATCH (e)-[r1:RELATION]->() "
            "OPTIONAL MATCH (e)<-[r2:RELATION]-() "
            "WITH e, count(m) AS mc, count(r1) AS rc1, count(r2) AS rc2 "
            "WHERE mc = 0 AND rc1 = 0 AND rc2 = 0 "
            "RETURN e.name AS name, e.type AS type LIMIT 50;"
        ))
        if rows:
            print(f"  Found {len(rows)} orphaned entities (showing up to 50):\n")
            for r in rows:
                print(f"  {r['name']:40s}  type={r['type']}")
            issues["WARNING"].append(f"{len(rows)}+ orphaned entities with no relationships")
        else:
            print("  No orphaned entities found.")

        # ---------------------------------------------------------------
        # 4. Self-referencing relationships
        # ---------------------------------------------------------------
        _header("4. SELF-REFERENCING RELATIONSHIPS")

        rows = _run(s, (
            "MATCH (a)-[r:RELATION]->(b) WHERE a = b "
            "RETURN a.name AS name, r.type AS rel_type LIMIT 20;"
        ))
        if rows:
            print(f"  Found {len(rows)} self-referencing relationships:\n")
            for r in rows:
                print(f"  {r['name']} --[{r['rel_type']}]--> (self)")
            issues["WARNING"].append(f"{len(rows)} self-referencing RELATION edges")
        else:
            print("  No self-referencing relationships found.")

        # ---------------------------------------------------------------
        # 5. Duplicate relationships between same entities
        # ---------------------------------------------------------------
        _header("5. DUPLICATE RELATIONSHIPS (same pair, same type)")

        rows = _run(s, (
            "MATCH (a)-[r:RELATION]->(b) "
            "WITH a, b, r.type AS rel_type, collect(r) AS rels "
            "WHERE size(rels) > 1 "
            "RETURN a.name AS source, b.name AS target, rel_type, size(rels) AS count "
            "ORDER BY count DESC LIMIT 30;"
        ))
        if rows:
            print(f"  Found {len(rows)} duplicate relationship pairs:\n")
            total_dupes = 0
            for r in rows:
                total_dupes += r["count"] - 1
                print(f"  {r['source']:25s} --[{r['rel_type']}]--> {r['target']:25s}  x{r['count']}")
            issues["WARNING"].append(f"{len(rows)} entity pairs with duplicate relationships ({total_dupes} extra edges)")
        else:
            print("  No duplicate relationships found.")

        # ---------------------------------------------------------------
        # 6. Entity name quality
        # ---------------------------------------------------------------
        _header("6. ENTITY NAME QUALITY")

        _subheader("Names with underscores (likely code/IDs, not proper names)")
        rows = _run(s, "MATCH (e:Entity) WHERE e.name =~ '.*[_].*' RETURN e.name AS name, e.type AS type LIMIT 30;")
        if rows:
            for r in rows:
                print(f"  {r['name']:40s}  type={r['type']}")
            issues["WARNING"].append(f"{len(rows)}+ entity names contain underscores")
        else:
            print("  None found.")

        _subheader("Very short names (< 3 chars)")
        rows = _run(s, "MATCH (e:Entity) WHERE size(e.name) < 3 RETURN e.name AS name, e.type AS type;")
        if rows:
            for r in rows:
                print(f"  '{r['name']}' type={r['type']}")
            issues["WARNING"].append(f"{len(rows)} entity names shorter than 3 characters")
        else:
            print("  None found.")

        _subheader("Very long names (> 50 chars)")
        rows = _run(s, "MATCH (e:Entity) WHERE size(e.name) > 50 RETURN e.name AS name, e.type AS type;")
        if rows:
            for r in rows:
                print(f"  '{r['name'][:60]}...' type={r['type']}")
            issues["WARNING"].append(f"{len(rows)} entity names longer than 50 characters")
        else:
            print("  None found.")

        # ---------------------------------------------------------------
        # 7. Document-Entity coverage
        # ---------------------------------------------------------------
        _header("7. DOCUMENT-ENTITY COVERAGE")

        _subheader("Document nodes")
        rows = _run(s, (
            "MATCH (d:Document) OPTIONAL MATCH (d)-[:MENTIONS]->(e) "
            "WITH d, count(e) AS entity_count "
            "RETURN min(entity_count) AS min_ent, toFloat(avg(entity_count)) AS avg_ent, "
            "max(entity_count) AS max_ent, count(d) AS total_docs, "
            "count(CASE WHEN entity_count = 0 THEN 1 END) AS docs_without;"
        ))
        if rows and rows[0]["total_docs"]:
            r = rows[0]
            print(f"  Total documents:        {r['total_docs']}")
            print(f"  Entities per doc:        min={r['min_ent']}  avg={r['avg_ent']:.1f}  max={r['max_ent']}")
            print(f"  Docs without entities:  {r['docs_without']}")
            if r["docs_without"] and r["docs_without"] > 0:
                pct = r["docs_without"] / r["total_docs"] * 100
                issues["INFO"].append(f"{r['docs_without']}/{r['total_docs']} documents ({pct:.0f}%) have no entities")
        else:
            print("  No Document nodes found.")
            issues["INFO"].append("No Document nodes in graph")

        _subheader("JiraIssue nodes")
        rows = _run(s, (
            "MATCH (d:JiraIssue) OPTIONAL MATCH (d)-[:MENTIONS]->(e) "
            "WITH d, count(e) AS entity_count "
            "RETURN min(entity_count) AS min_ent, toFloat(avg(entity_count)) AS avg_ent, "
            "max(entity_count) AS max_ent, count(d) AS total_issues, "
            "count(CASE WHEN entity_count = 0 THEN 1 END) AS issues_without;"
        ))
        if rows and rows[0]["total_issues"]:
            r = rows[0]
            print(f"  Total Jira issues:      {r['total_issues']}")
            print(f"  Entities per issue:      min={r['min_ent']}  avg={r['avg_ent']:.1f}  max={r['max_ent']}")
            print(f"  Issues without entities: {r['issues_without']}")
            if r["issues_without"] and r["issues_without"] > 0:
                pct = r["issues_without"] / r["total_issues"] * 100
                issues["INFO"].append(f"{r['issues_without']}/{r['total_issues']} Jira issues ({pct:.0f}%) have no entities")
        else:
            print("  No JiraIssue nodes found.")
            issues["INFO"].append("No JiraIssue nodes in graph")

        # ---------------------------------------------------------------
        # 8. ALIAS relationships
        # ---------------------------------------------------------------
        _header("8. ALIAS RELATIONSHIPS")

        rows = _run(s, "MATCH (a)-[:ALIAS]->(b) RETURN a.name AS from_name, b.name AS to_name;")
        if rows:
            print(f"  Found {len(rows)} ALIAS edges:\n")
            for r in rows:
                print(f"  {r['from_name']:30s}  -->  {r['to_name']}")
            issues["INFO"].append(f"{len(rows)} ALIAS relationships")
        else:
            print("  No ALIAS relationships found.")
            issues["INFO"].append("No ALIAS relationships in graph")

        # Also check bidirectional aliases (common pattern issue)
        rows = _run(s, (
            "MATCH (a)-[:ALIAS]->(b)-[:ALIAS]->(a) "
            "RETURN a.name AS name1, b.name AS name2;"
        ))
        if rows:
            _subheader("Bidirectional ALIAS edges (A->B and B->A)")
            for r in rows:
                print(f"  {r['name1']}  <-->  {r['name2']}")
            issues["WARNING"].append(f"{len(rows)} bidirectional ALIAS pairs (should be unidirectional)")

    # ---------------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------------
    _header("SUMMARY")

    for severity in ("CRITICAL", "WARNING", "INFO"):
        items = issues[severity]
        if items:
            print(f"\n  [{severity}] ({len(items)} items)")
            for item in items:
                print(f"    - {item}")

    critical = len(issues["CRITICAL"])
    warnings = len(issues["WARNING"])
    print(f"\n  Total: {critical} critical, {warnings} warnings, {len(issues['INFO'])} info")

    if critical > 0:
        print("\n  ACTION REQUIRED: Critical issues found that may cause wrong answers.")
    elif warnings > 0:
        print("\n  Graph has quality issues but no critical data integrity problems.")
    else:
        print("\n  Graph looks clean.")


def main() -> None:
    try:
        audit()
    except Exception as e:
        print(f"\nFATAL: Could not connect to Memgraph: {e}", file=sys.stderr)
        print("Make sure Memgraph is running on bolt://localhost:7687", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
