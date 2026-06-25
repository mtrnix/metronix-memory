# Inspecting the Qdrant Vector Store (Docker)

The Metronix Core stack runs Qdrant in the `metronix-full-qdrant` container.

| Setting | Value |
|---|---|
| Container | `metronix-full-qdrant` |
| Image | `qdrant/qdrant:v1.18.0` |
| REST port | `6335` → container `6333` |
| gRPC port | `6336` → container `6334` |
| Collection | `mem_docs_hybrid` |

Qdrant has no `psql`-style shell — it is driven through its REST API.
The commands below use `curl` against the host-mapped REST port `6335`.
Web dashboard: <http://localhost:6335/dashboard>

## Inspecting structure

```bash
# List collections
curl -s http://localhost:6335/collections | python3 -m json.tool

# Collection info: point count, vector config, payload schema
curl -s http://localhost:6335/collections/mem_docs_hybrid | python3 -m json.tool

# Just the point count
curl -s http://localhost:6335/collections/mem_docs_hybrid \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["points_count"])'
```

`mem_docs_hybrid` is a hybrid collection: a dense vector (`dense`, 768-dim, Cosine)
plus a sparse `bm25` vector.

## Reading points

```bash
# Scroll points with payload (vectors omitted for readability)
curl -s -X POST http://localhost:6335/collections/mem_docs_hybrid/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"limit": 100, "with_payload": true, "with_vector": false}' \
  | python3 -m json.tool

# Fetch a single point by id
curl -s http://localhost:6335/collections/mem_docs_hybrid/points/<POINT_ID> \
  | python3 -m json.tool
```

## Rendering points as Markdown

```bash
curl -s -X POST http://localhost:6335/collections/mem_docs_hybrid/points/scroll \
  -H 'Content-Type: application/json' \
  -d '{"limit": 100, "with_payload": true, "with_vector": false}' \
  | python3 -c '
import sys, json
pts = json.load(sys.stdin)["result"]["points"]
print("| id | title | source_id | workspace | role | chunk_type |")
print("|---|---|---|---|---|---|")
for p in pts:
    pl = p["payload"]
    print("| {} | {} | {} | {} | {} | {} |".format(
        p["id"][:12], pl.get("title",""), pl.get("source_id",""),
        pl.get("workspace_id",""), pl.get("source_role",""), pl.get("chunk_type","")))
'
```

Append `> qdrant_points.md` to save the table to a file.

Current output:

| id | title | source_id | workspace | role | chunk_type |
|---|---|---|---|---|---|
| 0da4723d-bea | product/open-core-boundaries.md | product-open-core-boundaries | MTRNIX | knowledge_base | standalone |
| de4af415-58f | product/legacy.md | product-legacy | MTRNIX | knowledge_base | standalone |

## Tips

- `points/scroll` paginates: pass the returned `next_page_offset` back as `"offset"` to continue.
- Add `"with_vector": true` to inspect the raw embeddings (large output).
- Filter by payload, e.g. only one workspace:

  ```bash
  curl -s -X POST http://localhost:6335/collections/mem_docs_hybrid/points/scroll \
    -H 'Content-Type: application/json' \
    -d '{"limit": 100, "with_payload": true,
         "filter": {"must": [{"key": "workspace_id", "match": {"value": "MTRNIX"}}]}}' \
    | python3 -m json.tool
  ```
