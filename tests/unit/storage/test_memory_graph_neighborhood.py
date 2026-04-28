"""Unit tests for get_memory_neighborhood (MTRNIX-324).

Uses a mocked Neo4j driver so no live Neo4j required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


def _make_row(**kwargs: Any) -> MagicMock:
    """Create a mock row that supports dict-style access."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: kwargs[k]
    return row


class TestGetMemoryNeighborhoodStorage:
    def test_returns_seed_only_for_unknown_seed(self) -> None:
        """When driver returns no rows the result contains only the seed id."""
        from metatron.storage.memory_graph import get_memory_neighborhood

        mock_session = MagicMock()
        # Both Cypher queries return no rows.
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.__enter__ = lambda self: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            result = get_memory_neighborhood("ws-1", "seed-id", 1)

        assert "seed-id" in result["record_ids"]
        assert result["edges"] == []

    def test_bridge_edge_includes_via_metadata(self) -> None:
        """Bridge edge (Agent) must surface via/via_id in metadata."""
        from metatron.storage.memory_graph import get_memory_neighborhood

        mock_session = MagicMock()
        mock_session.__enter__ = lambda self: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        # linked_result is empty; bridge_result has one Agent-bridged edge.
        linked_mock = MagicMock()
        linked_mock.__iter__ = lambda self: iter([])

        bridge_row = _make_row(
            source="seed-id",
            target="other-mem",
            rtype="REMEMBERS",
            via_label="Agent",
            via_id="agent-xyz",
        )
        bridge_mock = MagicMock()
        bridge_mock.__iter__ = lambda self: iter([bridge_row])

        mock_session.run.side_effect = [linked_mock, bridge_mock]
        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            result = get_memory_neighborhood("ws-1", "seed-id", 1)

        assert "other-mem" in result["record_ids"]
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["type"] == "REMEMBERS"
        assert edge["metadata"]["via"] == "Agent"
        assert edge["metadata"]["via_id"] == "agent-xyz"

    def test_workspace_param_passed_to_cypher(self) -> None:
        """Cypher must be invoked with workspace_id ($ws) parameter."""
        from metatron.storage.memory_graph import get_memory_neighborhood

        mock_session = MagicMock()
        mock_session.__enter__ = lambda self: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        empty_mock = MagicMock()
        empty_mock.__iter__ = lambda self: iter([])
        mock_session.run.return_value = empty_mock

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            get_memory_neighborhood("my-workspace", "seed-id", 2)

        # At least one call should have ws and seed params.
        call_params = [
            call[0][1] if len(call[0]) > 1 else call[1]
            for call in mock_session.run.call_args_list
        ]
        assert any("my-workspace" in str(p) for p in call_params)
        assert any("seed-id" in str(p) for p in call_params)

    def test_linked_query_uses_vanilla_cypher_no_apoc(self) -> None:
        """LINKED_TO traversal must use vanilla variable-length Cypher.

        APOC is not installed in the project's docker-compose Neo4j image, so
        any reliance on ``apoc.*`` procedures would silently produce zero
        memory-to-memory edges in production. Regression guard for MTRNIX-324.
        """
        from metatron.storage.memory_graph import get_memory_neighborhood

        mock_session = MagicMock()
        mock_session.__enter__ = lambda self: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        empty_mock = MagicMock()
        empty_mock.__iter__ = lambda self: iter([])
        mock_session.run.return_value = empty_mock

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            get_memory_neighborhood("ws-1", "seed-id", 2)

        # Inspect every Cypher string passed to session.run().
        cypher_strings = [call.args[0] for call in mock_session.run.call_args_list]
        assert cypher_strings, "expected at least one session.run() invocation"
        for cypher in cypher_strings:
            assert "apoc." not in cypher.lower(), (
                f"Cypher must not depend on APOC plugin (found in: {cypher!r})"
            )
        # Also confirm the LINKED_TO traversal uses vanilla variable-length syntax.
        linked_cypher = next(c for c in cypher_strings if "LINKED_TO" in c)
        assert "LINKED_TO*1.." in linked_cypher

    def test_linked_query_depth_interpolated_into_pattern(self) -> None:
        """``depth`` must be interpolated into the LINKED_TO pattern bound."""
        from metatron.storage.memory_graph import get_memory_neighborhood

        mock_session = MagicMock()
        mock_session.__enter__ = lambda self: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        empty_mock = MagicMock()
        empty_mock.__iter__ = lambda self: iter([])
        mock_session.run.return_value = empty_mock

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session

        with patch("metatron.storage.memory_graph.get_graph_driver", return_value=mock_driver):
            get_memory_neighborhood("ws-1", "seed-id", 3)

        cypher_strings = [call.args[0] for call in mock_session.run.call_args_list]
        linked_cypher = next(c for c in cypher_strings if "LINKED_TO" in c)
        assert "LINKED_TO*1..3" in linked_cypher
