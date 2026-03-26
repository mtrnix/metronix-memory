from metatron.core.config import Settings


def test_recall_top_n_defaults():
    s = Settings()
    assert s.recall_top_n_dense == 30
    assert s.recall_top_n_exact == 10
    assert s.recall_top_n_metadata == 10
    assert s.recall_top_n_graph == 5


def test_recall_top_n_from_env(monkeypatch):
    monkeypatch.setenv("RECALL_TOP_N_DENSE", "50")
    monkeypatch.setenv("RECALL_TOP_N_EXACT", "15")
    monkeypatch.setenv("RECALL_TOP_N_METADATA", "20")
    monkeypatch.setenv("RECALL_TOP_N_GRAPH", "8")
    s = Settings()
    assert s.recall_top_n_dense == 50
    assert s.recall_top_n_exact == 15
    assert s.recall_top_n_metadata == 20
    assert s.recall_top_n_graph == 8
