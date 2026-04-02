# Ingestion

## Overview
L2 — document ingestion pipeline. Takes raw `Document` objects from connectors,
processes them through parse → chunk → dedup → embed → store, and writes
results to Qdrant (vectors) and Neo4j (knowledge graph).

## Files

### `pipeline.py`
`IngestionPipeline` — main orchestrator.
Initialized with `LLMProviderInterface`, `VectorStoreInterface`, `ProcessorInterface`.

`ingest_documents(documents, workspace_id, settings) -> SyncResult`
— Full pipeline per document:
1. `extract_document_date()` — extracts best date from title/content/updated_at/created_at
2. File type detection → appropriate processor → `extract_text()`
3. `root_child_chunk()` or `chunk_text()` → list of chunks
4. `simhash()` + `DeduplicationIndex.is_duplicate()` → skip near-dups
5. Embedding via `LLMProviderInterface.embed()`
6. `VectorStoreInterface.upsert(workspace_id, chunks)`
7. Graph extraction: `_extract_graphs_parallel()` → `_write_doc_to_graph()` / `_write_jira_to_graph()`

`extract_document_date(title, content, updated_at, created_at) -> str`
— Priority: date in title → date in first 500 chars → updated_at → created_at → "".

`_extract_graphs_parallel(docs, workspace_id)` — ThreadPoolExecutor for concurrent NER extraction.
`_write_jira_to_graph(doc, workspace_id)` — Jira-specific graph schema (Issue → Sprint → Person).
`_write_doc_to_graph(doc, workspace_id)` — generic document NER → Neo4j.
`_register_persons(doc)` — adds author/assignee names to `AliasRegistry`.

### `chunking.py`
Two chunking strategies:

`root_child_chunk(text, max_child_chars, overlap) -> list[Chunk]`
— OpenMemory root-child pattern: one ROOT chunk (full doc summary) + multiple CHILD chunks.
ROOT has no content, just metadata. CHILD chunks reference ROOT via `parent_id`.
Uses sentence-aware splitting (`_split_sentences()` + `_merge_sentences_to_chunks()`).

`chunk_text(text, max_chars=2500, overlap=200) -> list[str]`
— Simple sliding window chunking. Returns plain strings (used when full Chunk objects not needed).

`simple_chunk(text, max_chars) -> list[str]`
— Naive character-boundary split. Fallback for very short texts.

### `dedup.py`
`simhash(text, shingle_size=4) -> int`
— 64-bit SimHash from character shingles. Used to detect near-duplicate chunks.

`hamming_distance(hash1, hash2) -> int` — popcount of XOR.

`is_near_duplicate(hash1, hash2, threshold=3) -> bool` — hamming distance ≤ threshold.

`DeduplicationIndex`
— In-memory set of seen simhashes. `add(hash)`, `is_duplicate(hash, threshold)`.
One instance per pipeline run, discarded after sync.

### `bm25.py`
BM25 sparse vector generation for Qdrant hybrid search.
`tokenize(text) -> list[str]` — lowercase, strip punctuation (EN + transliterated text).
`build_sparse_vector(text, vocab_size=30000) -> dict[int, float]`
— Consistent hash of tokens → sparse {token_hash: tf-idf weight} dict.
`vocab_size=30000` (configurable via `BM25_VOCAB_SIZE`).

### `sync.py`
`check_and_version_document(doc, postgres_store) -> tuple[bool, bool]`
— Checks if document changed (content hash comparison). Returns `(is_new, is_updated)`.
Creates `DocumentVersion` record on change.

`BackgroundSyncManager`
— Manages async background sync tasks per connection.
`start_sync(connection_id, connector, workspace_id)`
`stop_sync(connection_id)`
`get_status() -> dict[str, str]`

### `processors/`
File format processors implementing `ProcessorInterface`.

| File | Processor | Handles |
|------|-----------|---------|
| `pdf.py` | `PdfProcessor` | PDF via PyMuPDF (fitz) — 2-stage: tables as markdown, prose as text |
| `office.py` | `OfficeProcessor` | .docx (python-docx), .xlsx (openpyxl) |
| `text.py` | `TextProcessor` | .txt, .md, .csv, .log — minimal processing |
| `html.py` | `process_html()` | Confluence HTML → JSON decode → ftfy fix → markdownify → normalize |
| `tabular.py` | `process_tabular_file()` | CSV/Excel → `Row N: Col1: Val1, ...` format for RAG |
| `dates.py` | `extract_date_from_text()` | RU + EN date extraction (ISO, relative, named weekdays) |
| `titles.py` | `extract_title_from_body()` | Title from Confluence/Jira JSON body or Markdown |
| `translation.py` | `translate_to_english()` | RU→EN via LLM (`is_russian()`, `is_english()` detection) |

## Key Patterns
- **Sync pipeline** — all ingestion is synchronous (TODO: async migration)
- **Graph extraction workers** — `GRAPH_EXTRACTION_WORKERS=4` (ThreadPoolExecutor) for NER parallelism
- **Dedup per run** — `DeduplicationIndex` is created fresh per sync run, not persistent
- **SimHash threshold** — hamming distance ≤ 3 treated as near-duplicate
- **Date extraction priority** — title date > content date > connector timestamp (title date most reliable)

## Dependencies
- **Depends on**: `core.models` (Document, Chunk, SyncResult), `core.interfaces` (LLMProviderInterface, VectorStoreInterface, ProcessorInterface), `storage.qdrant`, `storage.neo4j_graph`, `storage.graph_ops`, `retrieval.alias_registry`
- **Depended on by**: `api.routes.chat` (upload endpoint), `api.routes.connections` (sync trigger), `connectors` (pass documents to pipeline)
