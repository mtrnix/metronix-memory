"""Neo4j knowledge graph audit — detect duplicates, orphans, quality issues.

Usage:
    python -m metronix.scripts.graph_audit
"""

from __future__ import annotations

import sys
from collections import defaultdict

from metronix.storage.neo4j_graph import get_graph_driver


def _run(session, query: str) -> list[list]:
    """Run a Cypher query and return results as list of positional lists."""
    result = session.run(query)
    return [list(record.values()) for record in result]


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

    driver = get_graph_driver()

    with driver.session() as s:
        # ---------------------------------------------------------------
        # 1. Basic stats
        # ---------------------------------------------------------------
        _header("1. BASIC STATS")

        _subheader("Node counts by label")
        rows = _run(s, "MATCH (n) RETURN labels(n), count(n) ORDER BY count(n) DESC;")
        total_nodes = 0
        for r in rows:
            lbl = r[0][0] if r[0] else "(no label)"
            print(f"  {lbl:20s}  {r[1]:>6}")
            total_nodes += r[1]
        print(f"  {'TOTAL':20s}  {total_nodes:>6}")

        _subheader("Relationship counts by type")
        rows = _run(s, "MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY count(r) DESC;")
        total_rels = 0
        for r in rows:
            print(f"  {r[0]:20s}  {r[1]:>6}")
            total_rels += r[1]
        print(f"  {'TOTAL':20s}  {total_rels:>6}")
        issues["INFO"].append(f"Graph has {total_nodes} nodes and {total_rels} relationships")

        # ---------------------------------------------------------------
        # 1b. Entity type distribution
        # ---------------------------------------------------------------
        _subheader("Entity types")
        rows = _run(s, ("MATCH (e:Entity) RETURN e.type, count(e) ORDER BY count(e) DESC;"))
        person_types: list[str] = []
        for r in rows:
            etype = r[0] or "(null)"
            print(f"  {etype:30s}  {r[1]:>4}")
            # Detect person-like types (English and Russian)
            low = etype.lower()
            if any(
                kw in low
                for kw in (
                    "person",
                    "персон",
                    "человек",
                    "member",
                    "developer",
                    "разработч",
                    "team member",
                    "сотрудник",
                    "user",
                    "участник",
                )
            ):
                person_types.append(etype)

        if person_types:
            issues["INFO"].append(f"Person-like entity types: {person_types}")
        else:
            issues["INFO"].append(
                "No person-like entity types detected — checking all entities for name duplicates"
            )

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
                "WITH e, count(m) "
                "RETURN e.name, e.workspace_id, e.type, count(m) "
                "ORDER BY e.name;"
            )
        else:
            # No person types found — check ALL entities for duplicates
            person_query = (
                "MATCH (e:Entity) "
                "OPTIONAL MATCH (e)<-[m:MENTIONS]-() "
                "WITH e, count(m) "
                "RETURN e.name, e.workspace_id, e.type, count(m) "
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
                    print(f"  {r[0]:40s}  type={r[2]}  ws={r[1]}  mentions={r[3]}")

            # Detect potential duplicates: normalize names and group
            normalized: dict[str, list[str]] = defaultdict(list)
            for r in rows:
                name = r[0]
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
            cyrillic_names = [r[0] for r in rows if any("\u0400" <= c <= "\u04ff" for c in r[0])]
            latin_names = [
                r[0]
                for r in rows
                if all(c < "\u0400" or c > "\u04ff" for c in r[0] if c.isalpha())
            ]
            if cyrillic_names and latin_names:
                print(f"  Cyrillic names ({len(cyrillic_names)}): {cyrillic_names[:10]}")
                print(f"  Latin names ({len(latin_names)}): {latin_names[:10]}")
                issues["WARNING"].append(
                    f"Mixed Cyrillic ({len(cyrillic_names)}) and Latin ({len(latin_names)}) person names — may contain cross-script duplicates"  # noqa: E501
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

        rows = _run(
            s,
            (
                "MATCH (e:Entity) "
                "OPTIONAL MATCH (e)<-[m:MENTIONS]-() "
                "OPTIONAL MATCH (e)-[r1:RELATION]->() "
                "OPTIONAL MATCH (e)<-[r2:RELATION]-() "
                "WITH e, count(m), count(r1), count(r2) "
                "WHERE count(m) = 0 AND count(r1) = 0 AND count(r2) = 0 "
                "RETURN e.name, e.type LIMIT 50;"
            ),
        )
        if rows:
            print(f"  Found {len(rows)} orphaned entities (showing up to 50):\n")
            for r in rows:
                print(f"  {r[0]:40s}  type={r[1]}")
            issues["WARNING"].append(f"{len(rows)}+ orphaned entities with no relationships")
        else:
            print("  No orphaned entities found.")

        # ---------------------------------------------------------------
        # 4. Self-referencing relationships
        # ---------------------------------------------------------------
        _header("4. SELF-REFERENCING RELATIONSHIPS")

        rows = _run(s, ("MATCH (a)-[r:RELATION]->(b) WHERE a = b RETURN a.name, r.type LIMIT 20;"))
        if rows:
            print(f"  Found {len(rows)} self-referencing relationships:\n")
            for r in rows:
                print(f"  {r[0]} --[{r[1]}]--> (self)")
            issues["WARNING"].append(f"{len(rows)} self-referencing RELATION edges")
        else:
            print("  No self-referencing relationships found.")

        # ---------------------------------------------------------------
        # 5. Duplicate relationships between same entities
        # ---------------------------------------------------------------
        _header("5. DUPLICATE RELATIONSHIPS (same pair, same type)")

        rows = _run(
            s,
            (
                "MATCH (a)-[r:RELATION]->(b) "
                "WITH a, b, r.type, count(r) "
                "WHERE count(r) > 1 "
                "RETURN a.name, b.name, r.type, count(r) "
                "ORDER BY count(r) DESC LIMIT 30;"
            ),
        )
        if rows:
            print(f"  Found {len(rows)} duplicate relationship pairs:\n")
            total_dupes = 0
            for r in rows:
                total_dupes += r[3] - 1
                print(f"  {r[0]:25s} --[{r[2]}]--> {r[1]:25s}  x{r[3]}")
            issues["WARNING"].append(
                f"{len(rows)} entity pairs with duplicate relationships ({total_dupes} extra edges)"  # noqa: E501
            )
        else:
            print("  No duplicate relationships found.")

        # ---------------------------------------------------------------
        # 6. Entity name quality
        # ---------------------------------------------------------------
        _header("6. ENTITY NAME QUALITY")

        _subheader("Names with underscores (likely code/IDs, not proper names)")
        rows = _run(
            s, "MATCH (e:Entity) WHERE e.name =~ '.*[_].*' RETURN e.name, e.type LIMIT 30;"
        )
        if rows:
            for r in rows:
                print(f"  {r[0]:40s}  type={r[1]}")
            issues["WARNING"].append(f"{len(rows)}+ entity names contain underscores")
        else:
            print("  None found.")

        _subheader("Very short names (< 3 chars)")
        rows = _run(s, "MATCH (e:Entity) WHERE size(e.name) < 3 RETURN e.name, e.type;")
        if rows:
            for r in rows:
                print(f"  '{r[0]}' type={r[1]}")
            issues["WARNING"].append(f"{len(rows)} entity names shorter than 3 characters")
        else:
            print("  None found.")

        _subheader("Very long names (> 50 chars)")
        rows = _run(s, "MATCH (e:Entity) WHERE size(e.name) > 50 RETURN e.name, e.type;")
        if rows:
            for r in rows:
                print(f"  '{r[0][:60]}...' type={r[1]}")
            issues["WARNING"].append(f"{len(rows)} entity names longer than 50 characters")
        else:
            print("  None found.")

        # ---------------------------------------------------------------
        # 7. Document-Entity coverage
        # ---------------------------------------------------------------
        _header("7. DOCUMENT-ENTITY COVERAGE")

        _subheader("Document nodes")
        rows = _run(
            s,
            (
                "MATCH (d:Document) OPTIONAL MATCH (d)-[:MENTIONS]->(e) "
                "WITH d, count(e) "
                "RETURN min(count(e)), avg(count(e)), "
                "max(count(e)), count(d), "
                "count(CASE WHEN count(e) = 0 THEN 1 END);"
            ),
        )
        if rows and rows[0][3]:
            r = rows[0]
            print(f"  Total documents:        {r[3]}")
            print(f"  Entities per doc:        min={r[0]}  avg={r[1]:.1f}  max={r[2]}")
            print(f"  Docs without entities:  {r[4]}")
            if r[4] and r[4] > 0:
                pct = r[4] / r[3] * 100
                issues["INFO"].append(f"{r[4]}/{r[3]} documents ({pct:.0f}%) have no entities")
        else:
            print("  No Document nodes found.")
            issues["INFO"].append("No Document nodes in graph")

        _subheader("JiraIssue nodes")
        rows = _run(
            s,
            (
                "MATCH (d:JiraIssue) OPTIONAL MATCH (d)-[:MENTIONS]->(e) "
                "WITH d, count(e) "
                "RETURN min(count(e)), avg(count(e)), "
                "max(count(e)), count(d), "
                "count(CASE WHEN count(e) = 0 THEN 1 END);"
            ),
        )
        if rows and rows[0][3]:
            r = rows[0]
            print(f"  Total Jira issues:      {r[3]}")
            print(f"  Entities per issue:      min={r[0]}  avg={r[1]:.1f}  max={r[2]}")
            print(f"  Issues without entities: {r[4]}")
            if r[4] and r[4] > 0:
                pct = r[4] / r[3] * 100
                issues["INFO"].append(f"{r[4]}/{r[3]} Jira issues ({pct:.0f}%) have no entities")
        else:
            print("  No JiraIssue nodes found.")
            issues["INFO"].append("No JiraIssue nodes in graph")

        # ---------------------------------------------------------------
        # 8. ALIAS relationships
        # ---------------------------------------------------------------
        _header("8. ALIAS RELATIONSHIPS")

        rows = _run(s, "MATCH (a)-[:ALIAS]->(b) RETURN a.name, b.name;")
        if rows:
            print(f"  Found {len(rows)} ALIAS edges:\n")
            for r in rows:
                print(f"  {r[0]:30s}  -->  {r[1]}")
            issues["INFO"].append(f"{len(rows)} ALIAS relationships")
        else:
            print("  No ALIAS relationships found.")
            issues["INFO"].append("No ALIAS relationships in graph")

        # Also check bidirectional aliases (common pattern issue)
        rows = _run(s, ("MATCH (a)-[:ALIAS]->(b)-[:ALIAS]->(a) RETURN a.name, b.name;"))
        if rows:
            _subheader("Bidirectional ALIAS edges (A->B and B->A)")
            for r in rows:
                print(f"  {r[0]}  <-->  {r[1]}")
            issues["WARNING"].append(
                f"{len(rows)} bidirectional ALIAS pairs (should be unidirectional)"
            )

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
        print(f"\nFATAL: Could not connect to Neo4j: {e}", file=sys.stderr)
        print("Make sure Neo4j is running on bolt://localhost:7687", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
