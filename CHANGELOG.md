# Changelog

## [Unreleased]

- feat: WS1 Stage 1 — core memory models and interfaces (MTRNIX-240)
- feat: memory hybrid search service (`MemorySearchService`) combining Qdrant vector, Neo4j graph, and Redis session legs with weighted blend and graceful degradation (MTRNIX-247)
- **Breaking**: Replace Memgraph with Neo4j Community Edition for knowledge graph storage
  - Docker image: `memgraph/memgraph:2.18.1` → `neo4j:5-community`
  - Env vars: `MEMGRAPH_*` → `NEO4J_*` (old names still work via aliases)
  - Internal: `storage/memgraph.py` → `storage/neo4j_graph.py`, all functions renamed
  - Cypher queries migrated from inline `_esc()` escaping to `$param` parameterized queries
  - Removed Memgraph write-lock (Neo4j handles concurrent read/write)
  - Removed Cypher syntax workarounds (keyword collisions, backtick escaping)
  - API: `/ready` response key changed from `memgraph` to `neo4j`
  - API: `/admin/status` response key changed from `memgraph` to `neo4j`
- feat: add Redis local dev setup — docker-compose, config, async storage client
- feat: activate root-child hierarchical chunking (MTRNIX-210)
- fix: auto-create Qdrant collection before ingestion (prevents 404 after cleanup)
- feat: graph-rebuild script for Memgraph recovery (`make graph-rebuild`)
- feat: retry failed graph writes after parallel extraction
- fix: deduplicate eval P@K by doc_label (removes inflated metrics from duplicate chunks)
- fix: verify Memgraph connection liveness before reuse (eliminates 30s timeout on defunct connections)
- fix: reduce GRAPH_EXTRACTION_WORKERS default to 1 (prevents Memgraph transaction conflicts)
- feat: clear graph entity cache on SYNC_COMPLETED event
- feat: two-phase grid search with caching — reduces runtime from months to minutes (MTRNIX-261)
- fix: update eval testset with current data (stale expected docs)
- feat: platform user mapping for Telegram/Slack/Discord channels (MTRNIX-263)
- feat: admin CRUD API for platform user mappings
- feat: AsyncQdrantVectorStore for async Qdrant access (MTRNIX-262 Phase 1)
- feat: async retrieval pipeline with parallel recall channels (MTRNIX-262 Phase 2)
- feat: async ingestion pipeline with AsyncQdrantVectorStore (MTRNIX-262 Phase 3)
- feat: document store layer — PostgreSQL as source of truth for ingestion (MTRNIX-265)
- feat: decouple graph extraction from sync — process from PostgreSQL separately (MTRNIX-266)
- feat: adaptive RRF fusion constant based on dense/sparse overlap (MTRNIX-211, default off — needs tuning)
- feat: transitive alias resolution via graph — 1..3 hop BFS over ALIAS edges (MTRNIX-212)
- feat: persistent deduplication index — SimHash fingerprints in PostgreSQL (MTRNIX-213)
- feat: push temporal filtering into Cypher queries + Memgraph indexes (MTRNIX-214)
- feat: HyDE for short/vague queries — hypothetical document embeddings (MTRNIX-215, default off)
- feat: SPLADE learned sparse representations replacing BM25 (MTRNIX-216)
- feat: SPLADE refactored into standalone microservice (MTRNIX-216 Phase 2)
