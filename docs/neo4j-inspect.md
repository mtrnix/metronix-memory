# Inspecting the Neo4j Graph (Docker)

The Metronix Core stack runs Neo4j in the `metronix-full-neo4j` container.

| Setting | Value |
|---|---|
| Container | `metronix-full-neo4j` |
| Image | `neo4j:5-community` |
| Bolt port | `7688` → container `7687` |
| HTTP / Browser | `7475` → container `7474` |
| User | `neo4j` |
| Password | from `.env` (`NEO4J_PASSWORD=neo4j/<password>`) |

Neo4j is queried with Cypher via `cypher-shell` inside the container.
Browser UI: <http://localhost:7475> (connect with bolt `bolt://localhost:7688`).

> The snippets below read the password from the container's `NEO4J_PASSWORD` env var into
> a shell variable `$PW`, so the secret never appears in your command. Run the `PW=...`
> line first in your shell session, then the `cypher-shell` commands reuse it.

```bash
# Load the password into $PW for the current shell session
PW=$(docker exec metronix-full-neo4j env | grep NEO4J_PASSWORD | cut -d/ -f2)
```

## Inspecting structure

```bash
# Node counts by label
docker exec metronix-full-neo4j cypher-shell -u neo4j -p "$PW" \
  "MATCH (n) RETURN labels(n) AS labels, count(*) AS cnt ORDER BY cnt DESC;"

# Relationship counts by type
docker exec metronix-full-neo4j cypher-shell -u neo4j -p "$PW" \
  "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS cnt ORDER BY cnt DESC;"

# Property keys present on a label (handy before querying)
docker exec metronix-full-neo4j cypher-shell -u neo4j -p "$PW" \
  "MATCH (d:Document) RETURN keys(d) AS doc_keys LIMIT 1;"

# Full schema overview (labels, rel types, property keys, indexes)
docker exec metronix-full-neo4j cypher-shell -u neo4j -p "$PW" "CALL db.schema.visualization();"
```

## Reading data

```bash
# Document nodes
docker exec metronix-full-neo4j cypher-shell -u neo4j -p "$PW" \
  "MATCH (d:Document)
   RETURN d.doc_label AS doc_label, d.file_name AS file,
          d.workspace_id AS ws, d.upload_time AS uploaded
   ORDER BY d.file_name;"

# The User -[:UPLOADED]-> Document graph
docker exec metronix-full-neo4j cypher-shell -u neo4j -p "$PW" \
  "MATCH (u:User)-[:UPLOADED]->(d:Document)
   RETURN u.user_id AS user, d.doc_label AS doc_label,
          d.file_name AS file, d.workspace_id AS ws
   ORDER BY d.file_name;"
```

## Rendering results as Markdown

`cypher-shell` has no markdown format, so build the table in Cypher and strip the
default header/borders with `--format plain`:

```bash
docker exec metronix-full-neo4j cypher-shell -u neo4j -p "$PW" --format plain \
  "MATCH (u:User)-[:UPLOADED]->(d:Document)
   WITH collect('| ' + u.user_id + ' | ' + d.doc_label + ' | ' +
                d.file_name + ' | ' + d.workspace_id + ' |') AS rows
   UNWIND (['| user | doc_label | file | workspace |',
            '|---|---|---|---|'] + rows) AS line
   RETURN line;" \
  | tail -n +2 | tr -d '\"'
```

(`tail -n +2` drops the `line` column header; `tr -d '\"'` removes the quotes
`--format plain` puts around string values.) Append `> neo4j_graph.md` to save it.

Current output:

| user | doc_label | file | workspace |
|---|---|---|---|
| system | product-open-core-boundaries | product/open-core-boundaries.md | MTRNIX |
| system | product-legacy | product/legacy.md | MTRNIX |

## Tips

- `cypher-shell` formats: `--format verbose` (default, bordered), `plain` (no borders), `auto`.
- Pipe a `.cypher` file in: `docker exec -i metronix-full-neo4j cypher-shell -u neo4j -p "$PW" < query.cypher`
- `Document` node properties: `doc_id`, `doc_label`, `file_name`, `workspace_id`, `user_id`, `upload_time`, `raw_text`.
- `User` node properties: `user_id`, `workspace_id`.
- Visualize a subgraph in the Browser UI at <http://localhost:7475>: `MATCH p=(u:User)-[:UPLOADED]->(d:Document) RETURN p`.
