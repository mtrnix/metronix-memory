# Structured Evidence Packs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat fragment list with structured evidence packs grouped by source role, with explicit PRIMARY/SUPPORTING markers for better-grounded LLM answers.

**Architecture:** Connectors declare `source_role` (class attribute), which flows through `Document` → ingestion pipeline → Qdrant payload → recall → `_collect_frags()` (now returns `list[dict]`) → `_mark_evidence_role()` → `_build_ctx()` (grouped markdown). System prompt gets atomic evidence rules.

**Tech Stack:** Python 3.12+, FastAPI, Qdrant, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-evidence-packs-design.md`

---

### Task 1: Add `source_role` to ConnectorInterface and connector classes

**Files:**
- Modify: `src/metatron/core/interfaces.py:26-33` — add class attribute
- Modify: `src/metatron/connectors/jira.py:24` — `source_role = "task_tracker"`
- Modify: `src/metatron/connectors/github.py:19` — `source_role = "task_tracker"`
- Modify: `src/metatron/connectors/slack_history.py:19` — `source_role = "communication"`
- Modify: `src/metatron/connectors/files.py:20` — `source_role = "user_upload"`
- Modify: `src/metatron/connectors/confluence.py:21` — keep default (no change needed)
- Modify: `src/metatron/connectors/notion.py:26` — keep default (no change needed)
- Modify: `src/metatron/connectors/gdrive.py:19` — keep default (no change needed)
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing tests for connector source_role**

```python
# tests/unit/test_evidence_packs.py
"""Tests for structured evidence packs — source roles, marking, grouping, context assembly."""

from __future__ import annotations


class TestConnectorSourceRoles:
    """Verify each connector declares the correct source_role."""

    def test_connector_interface_default(self) -> None:
        from metatron.core.interfaces import ConnectorInterface
        assert ConnectorInterface.source_role == "knowledge_base"

    def test_jira_connector_role(self) -> None:
        from metatron.connectors.jira import JiraConnector
        assert JiraConnector.source_role == "task_tracker"

    def test_github_connector_role(self) -> None:
        from metatron.connectors.github import GitHubConnector
        assert GitHubConnector.source_role == "task_tracker"

    def test_slack_history_connector_role(self) -> None:
        from metatron.connectors.slack_history import SlackHistoryConnector
        assert SlackHistoryConnector.source_role == "communication"

    def test_files_connector_role(self) -> None:
        from metatron.connectors.files import FilesConnector
        assert FilesConnector.source_role == "user_upload"

    def test_confluence_connector_role(self) -> None:
        from metatron.connectors.confluence import ConfluenceConnector
        assert ConfluenceConnector.source_role == "knowledge_base"

    def test_notion_connector_role(self) -> None:
        from metatron.connectors.notion import NotionConnector
        assert NotionConnector.source_role == "knowledge_base"

    def test_gdrive_connector_role(self) -> None:
        from metatron.connectors.gdrive import GDriveConnector
        assert GDriveConnector.source_role == "knowledge_base"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_evidence_packs.py::TestConnectorSourceRoles -v`
Expected: FAIL — `ConnectorInterface` has no attribute `source_role`

- [ ] **Step 3: Add `source_role` to ConnectorInterface**

In `src/metatron/core/interfaces.py`, add class attribute inside `ConnectorInterface` (after line 33, before the first `@abstractmethod`):

```python
class ConnectorInterface(ABC):
    """Fetches documents from an external data source.

    Each connector handles one source type (Confluence, Jira, etc.).
    Connectors are stateless — configuration comes from Connection objects.

    Lifecycle: configure(connection) → fetch(workspace_id) → documents
    """

    source_role: str = "knowledge_base"
```

- [ ] **Step 4: Set source_role on connector classes**

In `src/metatron/connectors/jira.py`, add after `class JiraConnector(ConnectorInterface):` line:

```python
class JiraConnector(ConnectorInterface):
    source_role = "task_tracker"
```

In `src/metatron/connectors/github.py`:

```python
class GitHubConnector(ConnectorInterface):
    source_role = "task_tracker"
```

In `src/metatron/connectors/slack_history.py`:

```python
class SlackHistoryConnector(ConnectorInterface):
    source_role = "communication"
```

In `src/metatron/connectors/files.py`:

```python
class FilesConnector(ConnectorInterface):
    source_role = "user_upload"
```

Confluence, Notion, GDrive — no change (inherit `"knowledge_base"` default).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestConnectorSourceRoles -v`
Expected: PASS (8/8)

- [ ] **Step 6: Commit**

```bash
git add src/metatron/core/interfaces.py src/metatron/connectors/jira.py src/metatron/connectors/github.py src/metatron/connectors/slack_history.py src/metatron/connectors/files.py tests/unit/test_evidence_packs.py
git commit -m "feat: add source_role class attribute to ConnectorInterface and connectors"
```

---

### Task 2: Add `source_role` to Document model, ingestion pipeline, and Qdrant _format_result

**Files:**
- Modify: `src/metatron/core/models.py:46-61` — add `source_role` field to Document
- Modify: `src/metatron/ingestion/pipeline.py:128-134` — add `source_role` param to `ingest_documents()`
- Modify: `src/metatron/ingestion/pipeline.py:208-218` — write `source_role` into chunk metadata
- Modify: `src/metatron/storage/qdrant.py:89-99` — extract `source_role` in `_format_result()`
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestSourceRoleDataFlow:
    """Verify source_role flows through Document → pipeline → Qdrant payload."""

    def test_document_has_source_role_field(self) -> None:
        from metatron.core.models import Document
        doc = Document(title="test", source_role="task_tracker")
        assert doc.source_role == "task_tracker"

    def test_document_source_role_default_empty(self) -> None:
        from metatron.core.models import Document
        doc = Document(title="test")
        assert doc.source_role == ""

    def test_format_result_includes_source_role(self) -> None:
        """_format_result extracts source_role from Qdrant payload."""
        from unittest.mock import MagicMock
        from metatron.storage.qdrant import QdrantVectorStore

        store = QdrantVectorStore.__new__(QdrantVectorStore)
        point = MagicMock()
        point.payload = {
            "data": "some text",
            "title": "Test",
            "type": "jira",
            "source_role": "task_tracker",
            "url": "",
            "date": "",
            "doc_label": "jira:123",
            "workspace_id": "ws1",
        }
        point.id = "abc123"
        result = store._format_result(point, 0.95)
        assert result["source_role"] == "task_tracker"

    def test_format_result_source_role_defaults_to_knowledge_base(self) -> None:
        """Chunks indexed before reindex get default source_role."""
        from unittest.mock import MagicMock
        from metatron.storage.qdrant import QdrantVectorStore

        store = QdrantVectorStore.__new__(QdrantVectorStore)
        point = MagicMock()
        point.payload = {"data": "some text", "title": "Old"}
        point.id = "old123"
        result = store._format_result(point, 0.8)
        assert result["source_role"] == "knowledge_base"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_evidence_packs.py::TestSourceRoleDataFlow -v`
Expected: FAIL — `Document` has no `source_role` parameter, `_format_result` doesn't return `source_role`

- [ ] **Step 3: Add `source_role` to Document dataclass**

In `src/metatron/core/models.py`, add field to `Document` dataclass (after `metadata` field, line 58):

```python
@dataclass
class Document:
    """A document fetched from a connector, before chunking."""

    id: str = field(default_factory=lambda: uuid4().hex)
    workspace_id: str = ""
    source_type: str = ""          # e.g. "confluence", "jira", "github"
    source_id: str = ""            # connector-specific unique ID
    title: str = ""
    content: str = ""
    url: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    source_role: str = ""          # e.g. "task_tracker", "knowledge_base", "user_upload", "communication"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

Note: `source_role` must come before `created_at`/`updated_at` since those have `field(default_factory=...)` and all fields with defaults must come after positional fields. Since all fields already have defaults, ordering is flexible — place it logically after `metadata`.

- [ ] **Step 4: Add `source_role` param to `ingest_documents()` and write to metadata**

In `src/metatron/ingestion/pipeline.py`, update function signature (line 128-134):

```python
def ingest_documents(
    documents: list[Document],
    workspace_id: str,
    connector_type: str = "",
    incremental: bool = False,
    plugin_manager=None,
    source_role: str = "knowledge_base",
) -> SyncResult:
```

In the metadata dict (line 208-218), add `source_role`:

```python
                metadata = {
                    "title": doc.title,
                    "type": doc.source_type or connector_type,
                    "source_id": doc.source_id,
                    "doc_label": doc.source_id,
                    "workspace_id": workspace_id,
                    "author": doc.author,
                    "date": doc_date,
                    "simhash": chunk_hash,
                    "source_role": source_role,
                    **(doc.metadata or {}),
                    "url": doc.url,  # after spread so doc.url takes precedence
                }
```

- [ ] **Step 5: Add `source_role` to `_format_result()` in qdrant.py**

In `src/metatron/storage/qdrant.py`, update `_format_result()` (line 89-99):

```python
    def _format_result(self, point: Any, score: float) -> Dict:
        """Format a Qdrant point into a standardized result dict."""
        payload = point.payload or {}
        data = payload.get("data") or payload.get("memory") or ""
        return {
            "id": str(point.id), "score": score, "memory": data, "data": data,
            "title": payload.get("title", ""), "type": payload.get("type", ""),
            "url": payload.get("url", ""),
            "date": payload.get("date", ""), "doc_label": payload.get("doc_label", ""),
            "workspace_id": payload.get("workspace_id", ""),
            "source_role": payload.get("source_role", "knowledge_base"),
            "payload": payload,
        }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestSourceRoleDataFlow -v`
Expected: PASS (4/4)

- [ ] **Step 7: Run full test suite to verify no regressions**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All 915+ tests pass

- [ ] **Step 8: Commit**

```bash
git add src/metatron/core/models.py src/metatron/ingestion/pipeline.py src/metatron/storage/qdrant.py tests/unit/test_evidence_packs.py
git commit -m "feat: source_role flows through Document → pipeline → Qdrant payload"
```

---

### Task 3: Pass `source_role` from callers (sync + chat upload)

Two callers write chunks to Qdrant: `_run_connection_sync()` in `connections.py` (uses `ingest_documents()`) and `_ingest_text()` in `chat.py` (calls `store.add_document()` directly with a metadata dict). Both need `source_role`.

**Files:**
- Modify: `src/metatron/api/routes/connections.py:666-670` — pass `source_role` to `ingest_documents()`
- Modify: `src/metatron/api/routes/chat.py:344-351` — add `source_role` to upload metadata dict
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing test for chat upload metadata**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestSourceRoleInCallers:
    """Verify source_role is passed from both sync and upload callers."""

    def test_ingest_documents_accepts_source_role_param(self) -> None:
        """ingest_documents signature includes source_role."""
        import inspect
        from metatron.ingestion.pipeline import ingest_documents
        sig = inspect.signature(ingest_documents)
        assert "source_role" in sig.parameters
        assert sig.parameters["source_role"].default == "knowledge_base"

    def test_chat_upload_metadata_has_source_role(self) -> None:
        """_ingest_text metadata dict includes source_role for uploads."""
        # We verify by reading the source — the metadata dict in _ingest_text
        # must contain "source_role": "user_upload".
        import ast
        import inspect
        from metatron.api.routes import chat
        source = inspect.getsource(chat._ingest_text)
        assert "source_role" in source
        assert "user_upload" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_evidence_packs.py::TestSourceRoleInCallers -v`
Expected: First test PASS (param added in Task 2), second FAIL — `_ingest_text` has no `source_role`

- [ ] **Step 3: Update `_run_connection_sync` to pass `source_role`**

In `src/metatron/api/routes/connections.py`, update lines 666-670. After `connector = registry.create(connector_type)` (line 647), the connector instance has `source_role`. Pass it to `ingest_documents`:

```python
        if documents:
            # ingest_documents is sync — run in thread pool
            result = await asyncio.to_thread(
                ingest_documents, documents, workspace_id, connector_type,
                source_role=connector.source_role,
            )
```

- [ ] **Step 4: Add `source_role` to chat upload metadata**

In `src/metatron/api/routes/chat.py`, update the metadata dict in `_ingest_text()` (line 344-351):

```python
    metadata = {
        "title": file_name,
        "type": "upload",
        "workspace_id": workspace_id,
        "user_id": user_id,
        "doc_label": doc_label,
        "source_role": "user_upload",
        "url": f"/api/v1/files/{file_id}/download?workspace_id={workspace_id}" if file_id and workspace_id else "",
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestSourceRoleInCallers -v`
Expected: PASS (2/2)

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add src/metatron/api/routes/connections.py src/metatron/api/routes/chat.py tests/unit/test_evidence_packs.py
git commit -m "feat: pass source_role from both sync and upload callers"
```

---

### Task 4: Refactor `_collect_frags()` to return `list[dict]`

This is the core refactor. Currently `_collect_frags()` returns `list[str]`. It needs to return `list[dict]` with metadata for evidence marking and grouped context assembly.

**Files:**
- Modify: `src/metatron/retrieval/search.py:239-279` — `_collect_frags()` returns `list[dict]`
- Modify: `src/metatron/retrieval/search.py:521` — callers updated
- Modify: `src/metatron/retrieval/search.py:529` — `get_graph_entities` call updated (takes texts from dicts)
- Modify: `src/metatron/retrieval/search.py:561-566` — `select_fragments_within_budget` call updated
- Modify: `src/metatron/retrieval/search.py:570` — `_build_ctx` call updated
- Modify: `src/metatron/retrieval/search.py:594-635` — trace logging updated
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing tests for dict-based _collect_frags**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestCollectFragsDicts:
    """_collect_frags returns list[dict] with metadata."""

    def test_returns_list_of_dicts(self) -> None:
        from metatron.retrieval.search import _collect_frags

        base = [
            {
                "memory": "Some text about architecture",
                "data": "Some text about architecture",
                "title": "Architecture Overview",
                "type": "confluence",
                "source_role": "knowledge_base",
                "doc_label": "confluence:123",
                "date": "2026-03-20",
                "payload": {},
            },
        ]
        frags, seen, total, doc_stats = _collect_frags(base, set(), 0)
        assert len(frags) == 1
        assert isinstance(frags[0], dict)
        assert frags[0]["text"] == "[CONFLUENCE] Architecture Overview\nSome text about architecture"
        assert frags[0]["source_type"] == "confluence"
        assert frags[0]["source_role"] == "knowledge_base"
        assert frags[0]["title"] == "Architecture Overview"
        assert frags[0]["date"] == "2026-03-20"
        assert frags[0]["doc_label"] == "confluence:123"

    def test_default_source_role_knowledge_base(self) -> None:
        """Fragments without source_role get default 'knowledge_base'."""
        from metatron.retrieval.search import _collect_frags

        base = [
            {
                "memory": "Old chunk without source_role",
                "data": "Old chunk without source_role",
                "title": "Old Doc",
                "type": "confluence",
                "doc_label": "c:1",
                "payload": {},
            },
        ]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert frags[0]["source_role"] == "knowledge_base"

    def test_dedup_by_text_hash(self) -> None:
        """Duplicate fragments are deduplicated by hash of first 200 chars."""
        from metatron.retrieval.search import _collect_frags

        item = {
            "memory": "Same text",
            "data": "Same text",
            "title": "Doc",
            "type": "confluence",
            "source_role": "knowledge_base",
            "doc_label": "c:1",
            "payload": {},
        }
        frags, _, _, _ = _collect_frags([item, item], set(), 0)
        assert len(frags) == 1

    def test_doc_stats_still_tracked(self) -> None:
        """FinOps doc_stats tracking works with dict fragments."""
        from metatron.retrieval.search import _collect_frags

        base = [
            {
                "memory": "Task implementation details",
                "data": "Task implementation details",
                "title": "MTRNIX-104",
                "type": "jira",
                "source_role": "task_tracker",
                "doc_label": "jira:104",
                "payload": {},
            },
        ]
        frags, _, _, doc_stats = _collect_frags(base, set(), 0)
        assert "jira:104" in doc_stats
        assert doc_stats["jira:104"]["title"] == "MTRNIX-104"
        assert doc_stats["jira:104"]["fetch_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_evidence_packs.py::TestCollectFragsDicts -v`
Expected: FAIL — `_collect_frags` returns `list[str]`, not `list[dict]`

- [ ] **Step 3: Refactor `_collect_frags()` to return `list[dict]`**

In `src/metatron/retrieval/search.py`, replace `_collect_frags` function (lines 239-279):

```python
def _collect_frags(
    base: list[dict], seen: set[int], total: int,
) -> tuple[list[dict], set[int], int, dict[str, dict]]:
    frags: list[dict] = []
    doc_stats: dict[str, dict] = {}  # {doc_label: {title, word_count, fetch_count}}
    for mem in base:
        text = mem.get("memory") or mem.get("data") or ""
        if len(text) > _MAX_FRAG:
            text = text[:_MAX_FRAG] + "..."

        # Prefix with source label so the LLM knows the origin
        source_type = _result_type(mem)
        title = (mem.get("title")
                 or (mem.get("payload") or {}).get("title")
                 or "")
        if source_type != "unknown" or title:
            parts = []
            if source_type != "unknown":
                parts.append(f"[{source_type.upper()}]")
            if title:
                parts.append(title)
            text = " ".join(parts) + "\n" + text

        th = hash(text[:200])
        if th in seen:
            continue
        if total + len(text) > _MAX_TOTAL:
            break
        seen.add(th); total += len(text)

        source_role = (mem.get("source_role")
                       or (mem.get("payload") or {}).get("source_role")
                       or "knowledge_base")
        date = (mem.get("date")
                or (mem.get("payload") or {}).get("date")
                or "")
        dl = mem.get("doc_label") or (mem.get("payload") or {}).get("doc_label") or ""

        frags.append({
            "text": text,
            "source_type": source_type,
            "source_role": source_role,
            "title": title,
            "date": date,
            "doc_label": dl,
            "evidence_marker": "",  # set later by _mark_evidence_role
        })

        # Track per-document stats for FinOps cost savings
        if dl:
            words = len(text.split())
            if dl not in doc_stats:
                doc_stats[dl] = {"title": title, "word_count": 0, "fetch_count": 0}
            doc_stats[dl]["word_count"] += words
            doc_stats[dl]["fetch_count"] += 1
            if title:
                doc_stats[dl]["title"] = title
    return frags, seen, total, doc_stats
```

- [ ] **Step 4: Update all downstream consumers of `frags` in `hybrid_search_and_answer()`**

Several places in `search.py` treat `frags` as `list[str]`. Update each:

**Line 529** — `get_graph_entities` needs text strings:
```python
        frag_texts = [f["text"] for f in frags]
        g_ents = get_entities_by_doc_labels(dl, workspace_id) if dl else get_graph_entities(frag_texts, workspace_id)
```

**Line 561-566** — `select_fragments_within_budget` (will be adapted in Task 5, for now extract texts):
```python
    frag_texts_for_budget = [f["text"] for f in frags]
    selected_texts = select_fragments_within_budget(
        frag_texts_for_budget,
        max_tokens=_s.llm_context_max_tokens,
        answer_reserve_tokens=_s.llm_answer_reserve_tokens,
        graph_tokens=g_tokens,
    )
    # Filter frags to only those whose text was selected
    selected_text_set = set(selected_texts)
    frags = [f for f in frags if f["text"] in selected_text_set]
```

**Line 570** — `_build_ctx` needs text list (will be refactored in Task 7, for now extract texts):
```python
    ctx = _build_ctx(rq if use_schema else query, lang, [f["text"] for f in frags], g_ents, g_rels, g_docs)
```

**Line 594** — trace logging:
```python
        _token_budget_used = sum(len(f["text"]) for f in frags) // 4 if frags else 0
```

**Line 598** — fragments field in trace:
```python
            "fragments": frags,
```
(Already dicts — trace consumers handle this.)

**Line 635** — `source_word_count`:
```python
            source_word_count = sum(len(f["text"].split()) for f in frags) if frags else 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestCollectFragsDicts -v`
Expected: PASS (4/4)

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All tests pass. If any test breaks because it expected `frags` to be `list[str]`, update those tests to handle `list[dict]`.

- [ ] **Step 7: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_evidence_packs.py
git commit -m "refactor: _collect_frags returns list[dict] with source metadata"
```

---

### Task 5: Adapt `select_fragments_within_budget()` for `list[dict]`

**Files:**
- Modify: `src/metatron/retrieval/token_budget.py:103-147` — accept/return `list[dict]`
- Modify: `src/metatron/retrieval/search.py:561-566` — simplify caller (remove text extraction workaround from Task 4)
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestTokenBudgetWithDicts:
    """select_fragments_within_budget works with list[dict] fragments."""

    def test_accepts_dict_fragments(self) -> None:
        from metatron.retrieval.token_budget import select_fragments_within_budget

        frags = [
            {"text": "Short fragment one.", "source_role": "task_tracker", "evidence_marker": "PRIMARY"},
            {"text": "Short fragment two.", "source_role": "knowledge_base", "evidence_marker": "SUPPORTING"},
        ]
        result = select_fragments_within_budget(frags, max_tokens=10000)
        assert len(result) == 2
        assert all(isinstance(f, dict) for f in result)
        assert result[0]["source_role"] == "task_tracker"

    def test_budget_truncation_preserves_metadata(self) -> None:
        from metatron.retrieval.token_budget import select_fragments_within_budget

        frags = [
            {"text": "A" * 4000, "source_role": "task_tracker", "evidence_marker": "PRIMARY"},
            {"text": "B" * 4000, "source_role": "knowledge_base", "evidence_marker": "SUPPORTING"},
            {"text": "C" * 4000, "source_role": "communication", "evidence_marker": "SUPPORTING"},
        ]
        # Budget of 2500 tokens ~ 10000 chars, should fit first 2 but not 3rd
        result = select_fragments_within_budget(frags, max_tokens=2500)
        assert len(result) <= 2
        assert all("source_role" in f for f in result)

    def test_backwards_compat_with_str_fragments(self) -> None:
        """Still works with list[str] for backward compatibility during migration."""
        from metatron.retrieval.token_budget import select_fragments_within_budget

        frags = ["Fragment one text.", "Fragment two text."]
        result = select_fragments_within_budget(frags, max_tokens=10000)
        assert len(result) == 2
        assert all(isinstance(f, str) for f in result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_evidence_packs.py::TestTokenBudgetWithDicts -v`
Expected: FAIL — `select_fragments_within_budget` doesn't handle dicts

- [ ] **Step 3: Update `select_fragments_within_budget()` to handle both str and dict**

In `src/metatron/retrieval/token_budget.py`, replace `select_fragments_within_budget`:

```python
def select_fragments_within_budget(
    fragments: list[str] | list[dict],
    max_tokens: int = 10000,
    system_prompt_tokens: int = 500,
    answer_reserve_tokens: int = 1500,
    graph_tokens: int = 0,
) -> list[str] | list[dict]:
    """Select as many fragments as fit within the token budget.

    Budget = max_tokens - system_prompt - answer_reserve - graph_context,
    but never less than MIN_FRAGMENT_TOKENS.
    Fragments are already ranked by relevance (best first).
    Greedily adds fragments until the budget is exhausted.

    Accepts both list[str] (legacy) and list[dict] (evidence packs)
    where dict has a "text" key.

    Args:
        fragments: Relevance-ranked fragments (str or dict with "text" key).
        max_tokens: Total token budget for the LLM context window.
        system_prompt_tokens: Estimated tokens for the system prompt.
        answer_reserve_tokens: Tokens reserved for LLM answer generation.
        graph_tokens: Tokens already allocated to graph context.

    Returns:
        List of fragments (same type as input) that fit within the budget.
    """
    computed = max_tokens - system_prompt_tokens - answer_reserve_tokens - graph_tokens
    available = max(computed, MIN_FRAGMENT_TOKENS)

    selected: list = []
    used = 0

    for frag in fragments:
        frag_text = frag["text"] if isinstance(frag, dict) else frag
        frag_tokens = estimate_tokens(frag_text)
        if used + frag_tokens > available:
            if not selected:
                ratio = available / max(frag_tokens, 1)
                if isinstance(frag, dict):
                    truncated = {**frag, "text": frag_text[: int(len(frag_text) * ratio)]}
                else:
                    truncated = frag_text[: int(len(frag_text) * ratio)]
                selected.append(truncated)
            break
        selected.append(frag)
        used += frag_tokens

    logger.info("token_budget.selected",
                available=len(fragments), selected=len(selected),
                tokens_used=used, tokens_budget=available)
    return selected
```

- [ ] **Step 4: Simplify the caller in search.py**

In `src/metatron/retrieval/search.py`, replace the workaround from Task 4 (lines 561-566):

```python
    frags = select_fragments_within_budget(
        frags,
        max_tokens=_s.llm_context_max_tokens,
        answer_reserve_tokens=_s.llm_answer_reserve_tokens,
        graph_tokens=g_tokens,
    )
```

Remove the `frag_texts_for_budget`, `selected_texts`, `selected_text_set` lines from Task 4.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestTokenBudgetWithDicts -v`
Expected: PASS (3/3)

- [ ] **Step 6: Run full test suite + typecheck**

Run: `pytest tests/unit/ -v --tb=short && make typecheck`
Expected: All tests pass. If mypy flags the `list[str] | list[dict]` return type, add `from __future__ import annotations` and use `Union` type or adjust callers.

- [ ] **Step 7: Commit**

```bash
git add src/metatron/retrieval/token_budget.py src/metatron/retrieval/search.py tests/unit/test_evidence_packs.py
git commit -m "feat: select_fragments_within_budget handles dict fragments"
```

---

### Task 6: Implement `_mark_evidence_role()` with PROFILE_PRIMARY_ROLE mapping

**Files:**
- Modify: `src/metatron/retrieval/search.py` — add `PROFILE_PRIMARY_ROLE` dict and `_mark_evidence_role()` function
- Modify: `src/metatron/retrieval/search.py:521` — call `_mark_evidence_role` after `_collect_frags`
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestMarkEvidenceRole:
    """_mark_evidence_role labels fragments PRIMARY/SUPPORTING based on query profile."""

    def _make_frag(self, source_role: str) -> dict:
        return {
            "text": f"Fragment from {source_role}",
            "source_type": "test",
            "source_role": source_role,
            "title": "Test",
            "date": "",
            "doc_label": "t:1",
            "evidence_marker": "",
        }

    def test_execution_profile_primary_is_task_tracker(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "execution")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_documentation_profile_primary_is_knowledge_base(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "documentation")
        assert frags[0]["evidence_marker"] == "SUPPORTING"
        assert frags[1]["evidence_marker"] == "PRIMARY"

    def test_user_file_profile_primary_is_user_upload(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("user_upload"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "user_file")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_mixed_profile_all_supporting(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "mixed")
        assert all(f["evidence_marker"] == "SUPPORTING" for f in frags)

    def test_relationship_profile_primary_is_knowledge_base(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("knowledge_base"), self._make_frag("task_tracker")]
        _mark_evidence_role(frags, "relationship")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_temporal_profile_primary_is_task_tracker(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("communication")]
        _mark_evidence_role(frags, "temporal")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_unknown_profile_all_supporting(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker")]
        _mark_evidence_role(frags, "unknown_profile")
        assert frags[0]["evidence_marker"] == "SUPPORTING"

    def test_unknown_source_role_gets_supporting(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("some_new_connector")]
        _mark_evidence_role(frags, "execution")
        assert frags[0]["evidence_marker"] == "SUPPORTING"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_evidence_packs.py::TestMarkEvidenceRole -v`
Expected: FAIL — `_mark_evidence_role` doesn't exist

- [ ] **Step 3: Implement PROFILE_PRIMARY_ROLE and _mark_evidence_role**

In `src/metatron/retrieval/search.py`, add after the `_SOURCE_ICONS` dict (around line 282):

```python
# Maps query classifier profile → which source_role gets PRIMARY evidence marker.
# None means all fragments get SUPPORTING (zero behavior change for mixed/unknown).
PROFILE_PRIMARY_ROLE: dict[str, str | None] = {
    "execution":     "task_tracker",
    "documentation": "knowledge_base",
    "user_file":     "user_upload",
    "relationship":  "knowledge_base",
    "temporal":      "task_tracker",
    "mixed":         None,
}


def _mark_evidence_role(frags: list[dict], query_profile: str) -> None:
    """Label each fragment as PRIMARY or SUPPORTING based on query profile.

    Mutates frags in place. PRIMARY = source_role matches the expected
    primary source for this query profile. Everything else is SUPPORTING.
    """
    primary_role = PROFILE_PRIMARY_ROLE.get(query_profile)
    for frag in frags:
        if primary_role and frag["source_role"] == primary_role:
            frag["evidence_marker"] = "PRIMARY"
        else:
            frag["evidence_marker"] = "SUPPORTING"
```

- [ ] **Step 4: Wire _mark_evidence_role into hybrid_search_and_answer**

In `src/metatron/retrieval/search.py`, after line 521 (`_collect_frags` call):

```python
    frags, seen_h, total_c, doc_stats = _collect_frags(base, set(), 0)
    _mark_evidence_role(frags, classification["profile"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestMarkEvidenceRole -v`
Expected: PASS (8/8)

- [ ] **Step 6: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_evidence_packs.py
git commit -m "feat: _mark_evidence_role labels PRIMARY/SUPPORTING by query profile"
```

---

### Task 7: Refactor `_build_ctx()` for grouped markdown format

**Files:**
- Modify: `src/metatron/retrieval/search.py:319-329` — `_build_ctx` groups frags by source_role
- Modify: `src/metatron/retrieval/search.py:570` — update caller to pass dict frags
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestBuildCtxGrouped:
    """_build_ctx groups fragments by source_role with markdown sections."""

    def _make_frag(self, source_role: str, marker: str, source_type: str = "jira",
                   title: str = "Doc", date: str = "2026-03-25") -> dict:
        return {
            "text": f"[{source_type.upper()}] {title}\nContent from {source_role}",
            "source_type": source_type,
            "source_role": source_role,
            "title": title,
            "date": date,
            "doc_label": f"{source_type}:1",
            "evidence_marker": marker,
        }

    def test_primary_group_appears_first(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [
            self._make_frag("knowledge_base", "SUPPORTING", "confluence", "Arch Overview"),
            self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104"),
        ]
        ctx = _build_ctx("What is the team doing?", "en", frags, [], [], [])
        # Task tracker section (has PRIMARY) should appear before knowledge base
        tt_pos = ctx.find("## Task tracker sources")
        kb_pos = ctx.find("## Knowledge base sources")
        assert tt_pos < kb_pos
        assert "[PRIMARY]" in ctx
        assert "[SUPPORTING]" in ctx

    def test_empty_groups_skipped(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [
            self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104"),
        ]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "## Task tracker sources" in ctx
        assert "## Knowledge base sources" not in ctx
        assert "## Communication sources" not in ctx

    def test_all_supporting_no_primary_group(self) -> None:
        """When mixed profile (all SUPPORTING), groups appear in fixed order."""
        from metatron.retrieval.search import _build_ctx

        frags = [
            self._make_frag("knowledge_base", "SUPPORTING", "confluence", "Doc1"),
            self._make_frag("task_tracker", "SUPPORTING", "jira", "MTRNIX-99"),
        ]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        # Fixed order: knowledge_base before task_tracker
        kb_pos = ctx.find("## Knowledge base sources")
        tt_pos = ctx.find("## Task tracker sources")
        assert kb_pos < tt_pos

    def test_graph_context_preserved(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [self._make_frag("task_tracker", "PRIMARY", "jira", "J1")]
        g_ents = [{"name": "Metatron", "type": "System"}]
        g_rels = [{"source": "Metatron", "target": "RAG", "type": "uses"}]
        g_docs = ["doc:1"]
        ctx = _build_ctx("query", "en", frags, g_ents, g_rels, g_docs)
        assert "## Graph context" in ctx
        assert "Metatron" in ctx

    def test_date_in_fragment_header(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104", "2026-03-25")]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "(2026-03-25)" in ctx

    def test_fragment_without_date(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104", "")]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "()" not in ctx  # no empty parens
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_evidence_packs.py::TestBuildCtxGrouped -v`
Expected: FAIL — `_build_ctx` still takes `list[str]` frags

- [ ] **Step 3: Rewrite `_build_ctx` for grouped format**

In `src/metatron/retrieval/search.py`, replace `_build_ctx` (lines 319-329):

```python
# Fixed display order for source_role groups (when no PRIMARY group takes priority)
_SOURCE_ROLE_ORDER = ["knowledge_base", "task_tracker", "user_upload", "communication"]
_SOURCE_ROLE_LABELS = {
    "knowledge_base": "Knowledge base sources",
    "task_tracker": "Task tracker sources",
    "user_upload": "User upload sources",
    "communication": "Communication sources",
}


def _build_ctx(q, lang, frags, g_ents, g_rels, g_docs):
    jd = lambda o: json.dumps(o, ensure_ascii=False, indent=2)  # noqa: E731

    # -- Group fragments by source_role --
    groups: dict[str, list[dict]] = {}
    primary_group: str | None = None
    for f in frags:
        role = f["source_role"] if isinstance(f, dict) else "knowledge_base"
        groups.setdefault(role, []).append(f)
        if isinstance(f, dict) and f.get("evidence_marker") == "PRIMARY" and primary_group is None:
            primary_group = role

    # Build ordered list: primary group first, then fixed order
    ordered_roles: list[str] = []
    if primary_group:
        ordered_roles.append(primary_group)
    for role in _SOURCE_ROLE_ORDER:
        if role != primary_group and role in groups:
            ordered_roles.append(role)
    # Any unknown roles appended at end
    for role in groups:
        if role not in ordered_roles:
            ordered_roles.append(role)

    # -- Assemble fragment sections --
    frag_sections: list[str] = []
    for role in ordered_roles:
        label = _SOURCE_ROLE_LABELS.get(role, f"{role} sources")
        lines = [f"## {label}"]
        for f in groups[role]:
            marker = f.get("evidence_marker", "SUPPORTING")
            date_suffix = f" ({f['date']})" if f.get("date") else ""
            # Text already has [TYPE] Title\ncontent prefix from _collect_frags
            # Replace the first line with marker-prefixed version
            text_lines = f["text"].split("\n", 1)
            header = text_lines[0]
            body = text_lines[1] if len(text_lines) > 1 else ""
            lines.append(f"[{marker}] {header}{date_suffix}")
            if body:
                lines.append(body)
            lines.append("")  # blank line between fragments
        frag_sections.append("\n".join(lines))

    fragment_text = "\n".join(frag_sections)

    # -- Graph context (unchanged format) --
    graph_parts: list[str] = []
    if g_ents or g_rels or g_docs:
        graph_parts.append("## Graph context")
        if g_ents:
            graph_parts.append(f"Entities: {jd(g_ents)}")
        if g_rels:
            graph_parts.append(f"Relationships: {jd(g_rels)}")
        if g_docs:
            graph_parts.append(f"Related documents: {jd(g_docs)}")
    graph_text = "\n".join(graph_parts)

    return (
        f"⚠️ RESPOND ONLY IN {lang.upper()}. Translate all information to {lang} if needed.\n\n"
        f"User question:\n{q}\n\n"
        f"{fragment_text}\n\n"
        f"{graph_text}\n\n"
        f"Provide a coherent answer. LANGUAGE: {lang.upper()} ONLY."
    )
```

- [ ] **Step 4: Update caller to pass dict frags directly**

In `src/metatron/retrieval/search.py`, update line 570 — remove the text extraction:

```python
    ctx = _build_ctx(rq if use_schema else query, lang, frags, g_ents, g_rels, g_docs)
```

(No change needed here — `frags` is already `list[dict]` from Task 4, and `_build_ctx` now handles dicts.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestBuildCtxGrouped -v`
Expected: PASS (6/6)

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_evidence_packs.py
git commit -m "feat: _build_ctx groups fragments by source_role with markdown sections"
```

---

### Task 8: Update HYBRID_SYSTEM_PROMPT with evidence rules

**Files:**
- Modify: `src/metatron/retrieval/prompts.py:4-48` — add evidence rules, remove deduplicated lines
- Test: `tests/unit/test_evidence_packs.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestSystemPromptEvidenceRules:
    """HYBRID_SYSTEM_PROMPT contains evidence rules and no deduplicated lines."""

    def test_evidence_rules_section_exists(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "## Evidence rules" in HYBRID_SYSTEM_PROMPT

    def test_primary_supporting_mentioned(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "[PRIMARY]" in HYBRID_SYSTEM_PROMPT
        assert "[SUPPORTING]" in HYBRID_SYSTEM_PROMPT

    def test_citation_rule_present(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "cite the source" in HYBRID_SYSTEM_PROMPT

    def test_contradiction_handling_present(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "contradict" in HYBRID_SYSTEM_PROMPT

    def test_insufficient_context_rule_present(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "insufficient" in HYBRID_SYSTEM_PROMPT

    def test_deduplicated_line_removed_invent_facts(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "Do not invent facts that are not in the provided fragments." not in HYBRID_SYSTEM_PROMPT

    def test_deduplicated_line_removed_primary_source(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "Use text fragments as the primary source of facts." not in HYBRID_SYSTEM_PROMPT

    def test_source_references_preserved(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "[$[" in HYBRID_SYSTEM_PROMPT  # source reference markers preserved

    def test_language_rules_preserved(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "CRITICAL RULE: RESPONSE LANGUAGE" in HYBRID_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_evidence_packs.py::TestSystemPromptEvidenceRules -v`
Expected: FAIL — no "## Evidence rules" section, deduplicated lines still present

- [ ] **Step 3: Update HYBRID_SYSTEM_PROMPT**

In `src/metatron/retrieval/prompts.py`, replace `HYBRID_SYSTEM_PROMPT` (lines 4-48):

```python
HYBRID_SYSTEM_PROMPT = """\
You are a hybrid question-answering system that combines vector search results and knowledge graph data.

## CRITICAL RULE: RESPONSE LANGUAGE
You MUST respond ENTIRELY in {response_language}. This is non-negotiable.
- If the user's question is in English, your ENTIRE response must be in English, even if all context documents are in Russian.
- If the user's question is in Russian, your ENTIRE response must be in Russian, even if all context documents are in English.
- NEVER mix languages in your response.
- Translate any facts from the context into {response_language} if needed.

## Your task:
- Answer the user's question using the provided context.
- Search results are labeled with their source: [CONFLUENCE], [JIRA], etc.
- Use ALL available sources to build a complete answer.
- For questions about team activities: combine Jira tasks (specific work items) with Confluence context (processes, architecture, decisions).
- For technical questions: prefer Confluence documentation, supplement with Jira implementation details.
- Use entities and relationships from the graph to clarify context and explain connections.
- If there are non-trivial dependencies between entities, mention them.
- Respond with coherent text, not JSON or raw data listings.
- If the user greets you or engages in small talk, respond warmly and briefly describe your \
capabilities. Do NOT reference search results for greetings.

## Evidence rules
- Fragments marked [PRIMARY] are the most relevant sources. Prioritize them.
- Fragments marked [SUPPORTING] provide additional context. Use to corroborate.
- When stating a fact, cite the source: "according to [JIRA] MTRNIX-104..." \
or "per [CONFLUENCE] Architecture Overview..."
- If a fact appears in only one source, note this: "(based on [SOURCE] only)"
- If sources contradict each other, state both versions with their sources.
- If the context is insufficient to answer, say so directly. Do not guess.
- Never mix facts from context with hypotheses or general knowledge.

## Source references
When you mention a specific document, ticket, or page title in your answer, wrap its name in \
reference markers: [$[title]$]. Examples:
- "According to [$[Architecture Overview]$], the system uses 6 layers..."
- "In [$[MTRNIX-108]$], Vadim is implementing the auth module..."
- "The report [$[report.pdf]$] contains Q4 results."
Only wrap titles that come from the provided context (search results, graph data). \
Do NOT wrap generic terms, concepts, or made-up names.

## Response length guidelines
- For questions about team activity ("what is the team doing", "what did the team do last week"):
  Keep it concise. List tasks with assignee and status. Max 5-7 bullet points. No architectural context unless explicitly asked.
- For questions about a specific person ("what is [person] doing", "who is working on [task]"):
  List only their tasks with status. 3-5 sentences max.
- For factual questions ("what is Metatron", "what is RAG", "explain [concept]"):
  2-3 paragraphs max. Focus on the core answer, skip implementation details.
- For general questions: answer in proportion to complexity. Simple question = short answer.
- NEVER pad the answer with architectural context, development methodology, or background information unless the user specifically asks for it.

REMINDER: Your response MUST be entirely in {response_language}. No exceptions.\
"""
```

Changes from original:
1. **Removed**: `"Use text fragments as the primary source of facts."` (line 16) — replaced by evidence rules
2. **Removed**: `"Do not invent facts that are not in the provided fragments."` (line 23) — replaced by "Never mix facts..." + "If the context is insufficient..."
3. **Added**: `## Evidence rules` section after `## Your task`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_evidence_packs.py::TestSystemPromptEvidenceRules -v`
Expected: PASS (9/9)

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/metatron/retrieval/prompts.py tests/unit/test_evidence_packs.py
git commit -m "feat: add evidence rules to HYBRID_SYSTEM_PROMPT, remove deduplicated lines"
```

---

### Task 9: Integration — verify full pipeline and update trace logging

**Files:**
- Modify: `src/metatron/retrieval/search.py` — final cleanup of trace logging
- Test: `tests/unit/test_evidence_packs.py` — integration test

- [ ] **Step 1: Write integration test**

Append to `tests/unit/test_evidence_packs.py`:

```python
class TestEvidencePacksIntegration:
    """End-to-end test: marking + grouping + context assembly."""

    def test_full_pipeline_execution_profile(self) -> None:
        """Execution profile: task_tracker = PRIMARY, knowledge_base = SUPPORTING."""
        from metatron.retrieval.search import _collect_frags, _mark_evidence_role, _build_ctx

        base = [
            {
                "memory": "Implementing auth module, status: in progress",
                "data": "Implementing auth module, status: in progress",
                "title": "MTRNIX-104",
                "type": "jira",
                "source_role": "task_tracker",
                "doc_label": "jira:104",
                "date": "2026-03-25",
                "payload": {},
            },
            {
                "memory": "The system uses 6 architectural layers for separation of concerns",
                "data": "The system uses 6 architectural layers for separation of concerns",
                "title": "Architecture Overview",
                "type": "confluence",
                "source_role": "knowledge_base",
                "doc_label": "confluence:arch",
                "date": "2026-03-20",
                "payload": {},
            },
        ]

        frags, _, _, doc_stats = _collect_frags(base, set(), 0)
        assert len(frags) == 2
        assert all(isinstance(f, dict) for f in frags)

        _mark_evidence_role(frags, "execution")
        # Jira = task_tracker → PRIMARY for execution profile
        jira_frag = next(f for f in frags if f["source_type"] == "jira")
        conf_frag = next(f for f in frags if f["source_type"] == "confluence")
        assert jira_frag["evidence_marker"] == "PRIMARY"
        assert conf_frag["evidence_marker"] == "SUPPORTING"

        ctx = _build_ctx("What is the team doing?", "en", frags, [], [], [])
        # Task tracker section appears first (has PRIMARY)
        assert ctx.index("## Task tracker sources") < ctx.index("## Knowledge base sources")
        assert "[PRIMARY]" in ctx
        assert "[SUPPORTING]" in ctx
        assert "MTRNIX-104" in ctx
        assert "Architecture Overview" in ctx

    def test_full_pipeline_mixed_profile(self) -> None:
        """Mixed profile: all fragments SUPPORTING, fixed group order."""
        from metatron.retrieval.search import _collect_frags, _mark_evidence_role, _build_ctx

        base = [
            {
                "memory": "Some jira content",
                "data": "Some jira content",
                "title": "MTRNIX-99",
                "type": "jira",
                "source_role": "task_tracker",
                "doc_label": "jira:99",
                "payload": {},
            },
            {
                "memory": "Some confluence content",
                "data": "Some confluence content",
                "title": "Doc",
                "type": "confluence",
                "source_role": "knowledge_base",
                "doc_label": "confluence:1",
                "payload": {},
            },
        ]

        frags, _, _, _ = _collect_frags(base, set(), 0)
        _mark_evidence_role(frags, "mixed")

        assert all(f["evidence_marker"] == "SUPPORTING" for f in frags)

        ctx = _build_ctx("query", "en", frags, [], [], [])
        # No PRIMARY group → fixed order: knowledge_base before task_tracker
        kb_pos = ctx.find("## Knowledge base sources")
        tt_pos = ctx.find("## Task tracker sources")
        assert kb_pos < tt_pos

    def test_trace_format_with_dict_frags(self) -> None:
        """Trace logging calculations work with dict fragments."""
        frags = [
            {"text": "word1 word2 word3", "source_role": "task_tracker", "evidence_marker": "PRIMARY"},
            {"text": "word4 word5", "source_role": "knowledge_base", "evidence_marker": "SUPPORTING"},
        ]
        token_budget_used = sum(len(f["text"]) for f in frags) // 4
        source_word_count = sum(len(f["text"].split()) for f in frags)
        assert token_budget_used > 0
        assert source_word_count == 5
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/unit/test_evidence_packs.py::TestEvidencePacksIntegration -v`
Expected: PASS (3/3)

- [ ] **Step 3: Run full test suite — final regression check**

Run: `pytest tests/unit/ -v --tb=short`
Expected: All 915+ tests pass (may be slightly higher with new tests)

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_evidence_packs.py
git commit -m "test: add integration tests for evidence packs pipeline"
```

---

## Post-Implementation

After all tasks are complete:
1. **Run eval** — verify P@10/MRR/NDCG don't regress (context format change, not recall)
2. **Reindex** — full reindex to populate `source_role` in Qdrant payloads
3. **Manual spot-check** — 10 queries checking proper citation, uncertainty marking, PRIMARY/SUPPORTING behavior
