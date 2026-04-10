"""Tests for memory_graph Neo4j operations (WS1 Stage 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from metatron.core.models import MemoryRecord, MemoryScope


def _mock_driver():
    """Create a mock Neo4j driver with session context manager."""
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return mock_driver, mock_session


# ---------------------------------------------------------------------------
# Task 1: Core node operations
# ---------------------------------------------------------------------------


class TestUpsertMemoryNode:
    def test_creates_node_with_all_metadata(self) -> None:
        mock_driver, mock_session = _mock_driver()
        record = MemoryRecord(
            id="mem001",
            workspace_id="ws1",
            agent_id="agent1",
            scope=MemoryScope.PER_AGENT,
            source_type="conversation",
            content="should not appear in cypher",
            tags=["pref", "style"],
            importance_score=0.8,
            content_hash="abc123",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            session_id="sess1",
        )

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import upsert_memory_node

            upsert_memory_node(record)

        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args.args[0]
        params = mock_session.run.call_args.args[1]

        assert "MERGE (m:MemoryRecord" in cypher
        assert params["id"] == "mem001"
        assert params["ws"] == "ws1"
        assert params["agent_id"] == "agent1"
        assert params["scope"] == "per_agent"
        assert params["source_type"] == "conversation"
        assert params["importance_score"] == 0.8
        assert params["tags"] == ["pref", "style"]
        assert params["content_hash"] == "abc123"
        assert params["session_id"] == "sess1"
        # content must NOT be in params — it lives in Qdrant
        assert "content" not in params

    def test_handles_none_ttl(self) -> None:
        mock_driver, mock_session = _mock_driver()
        record = MemoryRecord(id="mem002", workspace_id="ws1", agent_id="a1")

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import upsert_memory_node

            upsert_memory_node(record)

        params = mock_session.run.call_args.args[1]
        assert params["ttl_expires_at"] is None

    def test_serializes_ttl_as_isoformat(self) -> None:
        mock_driver, mock_session = _mock_driver()
        ttl = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        record = MemoryRecord(
            id="mem003",
            workspace_id="ws1",
            agent_id="a1",
            ttl_expires_at=ttl,
        )

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import upsert_memory_node

            upsert_memory_node(record)

        params = mock_session.run.call_args.args[1]
        assert params["ttl_expires_at"] == "2026-06-01T12:00:00+00:00"


class TestGetMemoryNode:
    def test_returns_dict_when_found(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "m": {"id": "mem001", "workspace_id": "ws1", "agent_id": "agent1"},
        }
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_memory_node

            result = get_memory_node("ws1", "mem001")

        assert result is not None
        assert result["id"] == "mem001"
        params = mock_session.run.call_args.args[1]
        assert params["ws"] == "ws1"
        assert params["id"] == "mem001"

    def test_returns_none_when_not_found(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_memory_node

            result = get_memory_node("ws1", "nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# Task 2: Delete operations
# ---------------------------------------------------------------------------


class TestDeleteMemoryNode:
    def test_returns_true_when_deleted(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.single.return_value = {"n": 1}
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import delete_memory_node

            assert delete_memory_node("ws1", "mem001") is True

        cypher = mock_session.run.call_args.args[0]
        assert "DETACH DELETE" in cypher
        assert "count(*)" in cypher  # not per-row count(m)

    def test_returns_false_when_not_found(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.single.return_value = {"n": 0}
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import delete_memory_node

            assert delete_memory_node("ws1", "nonexistent") is False


class TestDeleteAgentMemories:
    def test_deletes_all_agent_memories(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.single.return_value = {"n": 5}
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import delete_agent_memories

            count = delete_agent_memories("ws1", "agent1")

        assert count == 5
        cypher = mock_session.run.call_args.args[0]
        assert "count(*)" in cypher  # not per-row count(m)
        params = mock_session.run.call_args.args[1]
        assert params["ws"] == "ws1"
        assert params["agent_id"] == "agent1"

    def test_deletes_scoped_memories_only(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.single.return_value = {"n": 2}
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import delete_agent_memories

            count = delete_agent_memories("ws1", "agent1", scope="session")

        assert count == 2
        cypher = mock_session.run.call_args.args[0]
        assert "m.scope = $scope" in cypher
        params = mock_session.run.call_args.args[1]
        assert params["scope"] == "session"

    def test_returns_zero_when_no_match(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import delete_agent_memories

            assert delete_agent_memories("ws1", "ghost") == 0


# ---------------------------------------------------------------------------
# Task 3: Relationship edge operations
# ---------------------------------------------------------------------------


class TestLinkAgentMemory:
    def test_creates_agent_and_remembers_edge(self) -> None:
        mock_driver, mock_session = _mock_driver()

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import link_agent_memory

            link_agent_memory("ws1", "agent1", "mem001")

        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args.args[0]
        params = mock_session.run.call_args.args[1]
        assert "MERGE (a:Agent" in cypher
        assert "MERGE (a)-[:REMEMBERS" in cypher
        assert params["agent_id"] == "agent1"
        assert params["record_id"] == "mem001"
        assert "since" in params


class TestLinkMemoryEntity:
    def test_creates_about_edge_with_relevance(self) -> None:
        mock_driver, mock_session = _mock_driver()

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import link_memory_entity

            link_memory_entity("ws1", "mem001", "Python", relevance=0.9)

        cypher = mock_session.run.call_args.args[0]
        params = mock_session.run.call_args.args[1]
        assert ":ABOUT" in cypher
        assert params["entity_name"] == "Python"
        assert params["relevance"] == 0.9

    def test_default_relevance_is_one(self) -> None:
        mock_driver, mock_session = _mock_driver()

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import link_memory_entity

            link_memory_entity("ws1", "mem001", "Python")

        params = mock_session.run.call_args.args[1]
        assert params["relevance"] == 1.0


class TestLinkMemorySession:
    def test_creates_session_and_from_session_edge(self) -> None:
        mock_driver, mock_session = _mock_driver()

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import link_memory_session

            link_memory_session("ws1", "mem001", "sess1", "agent1")

        cypher = mock_session.run.call_args.args[0]
        params = mock_session.run.call_args.args[1]
        assert "MERGE (s:Session" in cypher
        assert ":FROM_SESSION" in cypher
        assert params["session_id"] == "sess1"
        assert params["agent_id"] == "agent1"


class TestLinkMemoryDocument:
    def test_creates_derived_from_edge(self) -> None:
        mock_driver, mock_session = _mock_driver()

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import link_memory_document

            link_memory_document("ws1", "mem001", "doc123")

        cypher = mock_session.run.call_args.args[0]
        params = mock_session.run.call_args.args[1]
        assert ":DERIVED_FROM" in cypher
        assert params["doc_id"] == "doc123"


# ---------------------------------------------------------------------------
# Task 4: Query operations
# ---------------------------------------------------------------------------


class TestGetAgentMemories:
    def test_returns_memories_ordered_by_importance(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"m": {"id": "m1", "importance_score": 0.9}},
                    {"m": {"id": "m2", "importance_score": 0.5}},
                ]
            )
        )
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_agent_memories

            results = get_agent_memories("ws1", "agent1")

        assert len(results) == 2
        assert results[0]["id"] == "m1"
        cypher = mock_session.run.call_args.args[0]
        assert "REMEMBERS" in cypher
        assert "importance_score DESC" in cypher

    def test_filters_by_scope(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_agent_memories

            get_agent_memories("ws1", "agent1", scope="global")

        cypher = mock_session.run.call_args.args[0]
        params = mock_session.run.call_args.args[1]
        assert "m.scope = $scope" in cypher
        assert params["scope"] == "global"

    def test_respects_limit(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_agent_memories

            get_agent_memories("ws1", "agent1", limit=10)

        params = mock_session.run.call_args.args[1]
        assert params["limit"] == 10


class TestGetMemoriesAboutEntity:
    def test_returns_memories_linked_to_entity(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(
            return_value=iter([{"m": {"id": "m1"}, "relevance": 0.9}])
        )
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_memories_about_entity

            results = get_memories_about_entity("ws1", "Python")

        assert len(results) == 1
        assert results[0]["id"] == "m1"
        assert results[0]["relevance"] == 0.9
        cypher = mock_session.run.call_args.args[0]
        assert "ABOUT" in cypher


class TestGetMemoryRelationships:
    def test_returns_all_edges(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(
            return_value=iter(
                [
                    {"type": "REMEMBERS", "target_label": "Agent", "target_id": "agent1"},
                    {"type": "ABOUT", "target_label": "Entity", "target_id": "Python"},
                ]
            )
        )
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_memory_relationships

            results = get_memory_relationships("ws1", "mem001")

        assert len(results) == 2

    def test_returns_empty_list_for_unknown_memory(self) -> None:
        mock_driver, mock_session = _mock_driver()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            from metatron.storage.memory_graph import get_memory_relationships

            results = get_memory_relationships("ws1", "nope")

        assert results == []


# ---------------------------------------------------------------------------
# Task 5: Composite save helper
# ---------------------------------------------------------------------------


class TestSaveMemoryToGraph:
    @patch("metatron.storage.memory_graph.link_memory_document")
    @patch("metatron.storage.memory_graph.link_memory_session")
    @patch("metatron.storage.memory_graph.link_memory_entity")
    @patch("metatron.storage.memory_graph.link_agent_memory")
    @patch("metatron.storage.memory_graph.upsert_memory_node")
    def test_creates_node_and_agent_edge(
        self,
        mock_upsert,
        mock_link_agent,
        mock_link_entity,
        mock_link_session,
        mock_link_doc,
    ) -> None:
        record = MemoryRecord(id="mem001", workspace_id="ws1", agent_id="agent1")

        from metatron.storage.memory_graph import save_memory_to_graph

        save_memory_to_graph(record)

        mock_upsert.assert_called_once_with(record)
        mock_link_agent.assert_called_once_with("ws1", "agent1", "mem001")
        mock_link_entity.assert_not_called()
        mock_link_session.assert_not_called()
        mock_link_doc.assert_not_called()

    @patch("metatron.storage.memory_graph.link_memory_document")
    @patch("metatron.storage.memory_graph.link_memory_session")
    @patch("metatron.storage.memory_graph.link_memory_entity")
    @patch("metatron.storage.memory_graph.link_agent_memory")
    @patch("metatron.storage.memory_graph.upsert_memory_node")
    def test_links_session_when_session_id_present(
        self,
        mock_upsert,
        mock_link_agent,
        mock_link_entity,
        mock_link_session,
        mock_link_doc,
    ) -> None:
        record = MemoryRecord(
            id="mem001",
            workspace_id="ws1",
            agent_id="agent1",
            session_id="sess1",
        )

        from metatron.storage.memory_graph import save_memory_to_graph

        save_memory_to_graph(record)

        mock_link_session.assert_called_once_with("ws1", "mem001", "sess1", "agent1")

    @patch("metatron.storage.memory_graph.link_memory_document")
    @patch("metatron.storage.memory_graph.link_memory_session")
    @patch("metatron.storage.memory_graph.link_memory_entity")
    @patch("metatron.storage.memory_graph.link_agent_memory")
    @patch("metatron.storage.memory_graph.upsert_memory_node")
    def test_links_entities_and_documents(
        self,
        mock_upsert,
        mock_link_agent,
        mock_link_entity,
        mock_link_session,
        mock_link_doc,
    ) -> None:
        record = MemoryRecord(id="mem001", workspace_id="ws1", agent_id="agent1")

        from metatron.storage.memory_graph import save_memory_to_graph

        save_memory_to_graph(
            record,
            entity_names=["Python", "FastAPI"],
            document_ids=["doc1"],
        )

        assert mock_link_entity.call_count == 2
        mock_link_entity.assert_any_call("ws1", "mem001", "Python", relevance=1.0)
        mock_link_entity.assert_any_call("ws1", "mem001", "FastAPI", relevance=1.0)
        mock_link_doc.assert_called_once_with("ws1", "mem001", "doc1")
