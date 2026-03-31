"""Tests for transitive alias resolution via graph."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.storage.graph_ops import (
    resolve_entity_aliases_batch,
    resolve_transitive_aliases,
)


def _mock_alias_results(alias_graph: dict[str, list[str]]):
    """Build a side_effect for session.run that simulates _alias_query results.

    alias_graph: mapping from entity name to list of 1-hop alias names.
    """
    def run_side_effect(query_str: str):
        # Extract the entity name from the Cypher query string
        # _alias_query produces: ... e.name = 'SomeName' ...
        for name, aliases in alias_graph.items():
            if f"'{name}'" in query_str:
                results = []
                for alias in aliases:
                    node = MagicMock()
                    node.get.side_effect = lambda key, a=alias: a if key == "name" else None
                    results.append((node,))
                return results
        return []
    return run_side_effect


@patch("metatron.storage.graph_ops.get_memgraph_driver")
def test_no_aliases(mock_driver):
    """Entity with no ALIAS edges returns just {entity_name}."""
    session = MagicMock()
    session.run.return_value = []
    mock_driver.return_value.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    mock_driver.return_value.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )

    result = resolve_transitive_aliases("ProjectX", workspace_id="ws1")
    assert result == {"ProjectX"}


@patch("metatron.storage.graph_ops.get_memgraph_driver")
def test_single_hop(mock_driver):
    """A has alias B -> returns {A, B}."""
    alias_graph = {"A": ["B"], "B": ["A"]}
    session = MagicMock()
    session.run.side_effect = _mock_alias_results(alias_graph)
    mock_driver.return_value.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    mock_driver.return_value.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )

    result = resolve_transitive_aliases("A", workspace_id="ws1", max_hops=1)
    assert result == {"A", "B"}


@patch("metatron.storage.graph_ops.get_memgraph_driver")
def test_multi_hop(mock_driver):
    """A->B->C chain, max_hops=3 -> {A, B, C}."""
    alias_graph = {"A": ["B"], "B": ["A", "C"], "C": ["B"]}
    session = MagicMock()
    session.run.side_effect = _mock_alias_results(alias_graph)
    mock_driver.return_value.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    mock_driver.return_value.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )

    result = resolve_transitive_aliases("A", workspace_id="ws1", max_hops=3)
    assert result == {"A", "B", "C"}


@patch("metatron.storage.graph_ops.get_memgraph_driver")
def test_cycle_handling(mock_driver):
    """A<->B bidirectional -> no infinite loop, returns {A, B}."""
    alias_graph = {"A": ["B"], "B": ["A"]}
    session = MagicMock()
    session.run.side_effect = _mock_alias_results(alias_graph)
    mock_driver.return_value.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    mock_driver.return_value.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )

    result = resolve_transitive_aliases("A", workspace_id="ws1", max_hops=10)
    assert result == {"A", "B"}


@patch("metatron.storage.graph_ops.get_memgraph_driver")
def test_max_hops_respected(mock_driver):
    """4-hop chain A->B->C->D->E, max_hops=3 -> stops at D, misses E."""
    alias_graph = {
        "A": ["B"], "B": ["A", "C"], "C": ["B", "D"], "D": ["C", "E"], "E": ["D"],
    }
    session = MagicMock()
    session.run.side_effect = _mock_alias_results(alias_graph)
    mock_driver.return_value.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    mock_driver.return_value.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )

    result = resolve_transitive_aliases("A", workspace_id="ws1", max_hops=3)
    assert result == {"A", "B", "C", "D"}
    assert "E" not in result


@patch("metatron.storage.graph_ops.get_memgraph_driver")
def test_batch_resolution(mock_driver):
    """Batch of 3 entities returns correct alias sets."""
    alias_graph = {"X": ["Y"], "Y": ["X"], "P": ["Q"], "Q": ["P"], "M": []}
    session = MagicMock()
    session.run.side_effect = _mock_alias_results(alias_graph)
    mock_driver.return_value.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    mock_driver.return_value.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )

    result = resolve_entity_aliases_batch(
        ["X", "P", "M"], workspace_id="ws1", max_hops=2,
    )
    assert result["X"] == {"X", "Y"}
    assert result["P"] == {"P", "Q"}
    assert result["M"] == {"M"}


def test_empty_input():
    """Empty list returns empty dict."""
    result = resolve_entity_aliases_batch([], workspace_id="ws1")
    assert result == {}
