"""X-Metronix-* header helpers (PROJ-372 P3)."""

from metronix.proxy.headers import enrichment_status, metronix_headers


def test_enrichment_full() -> None:
    assert enrichment_status([], requested=["memories"]) == "full"


def test_enrichment_partial() -> None:
    assert enrichment_status(["knowledge"], requested=["memories", "knowledge"]) == "partial"


def test_enrichment_skipped() -> None:
    assert (
        enrichment_status(["memories", "knowledge"], requested=["memories", "knowledge"])
        == "skipped"
    )


def test_headers_shape() -> None:
    h = metronix_headers(correlation_id="c", agent_id="A", enrichment="full", upstream_status=None)
    assert h["X-Metronix-Correlation-Id"] == "c"
    assert h["X-Metronix-Agent-Id"] == "A"
    assert h["X-Metronix-Enrichment"] == "full"
    assert "X-Metronix-Upstream-Status" not in h
    h2 = metronix_headers(correlation_id="c", agent_id="A", enrichment="full", upstream_status=200)
    assert h2["X-Metronix-Upstream-Status"] == "200"
