from metronix.core.config import Settings


def test_recall_top_n_defaults():
    s = Settings()
    assert s.recall_top_n_dense == 30
    assert s.recall_top_n_exact == 10
    assert s.recall_top_n_metadata == 10
    assert s.recall_top_n_graph == 5
    assert s.retrieval_graph_ppr_enabled is False
    assert s.retrieval_graph_ppr_alpha == 0.85
    assert s.retrieval_graph_ppr_max_iterations == 30
    assert s.retrieval_graph_ppr_max_nodes == 500


def test_recall_top_n_from_env(monkeypatch):
    monkeypatch.setenv("RECALL_TOP_N_DENSE", "50")
    monkeypatch.setenv("RECALL_TOP_N_EXACT", "15")
    monkeypatch.setenv("RECALL_TOP_N_METADATA", "20")
    monkeypatch.setenv("RECALL_TOP_N_GRAPH", "8")
    monkeypatch.setenv("METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED", "true")
    monkeypatch.setenv("METRONIX_RETRIEVAL_GRAPH_PPR_DENSE_ANCHOR_COUNT", "7")
    s = Settings()
    assert s.recall_top_n_dense == 50
    assert s.recall_top_n_exact == 15
    assert s.recall_top_n_metadata == 20
    assert s.recall_top_n_graph == 8
    assert s.retrieval_graph_ppr_enabled is True
    assert s.retrieval_graph_ppr_dense_anchor_count == 7
