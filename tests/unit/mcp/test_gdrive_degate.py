from metronix.mcp.tools.source_sync import _SCAFFOLD_CONNECTORS


def test_gdrive_no_longer_scaffold():
    assert "gdrive" not in _SCAFFOLD_CONNECTORS
    # slack_history/files remain scaffolds (still unimplemented).
    assert "slack_history" in _SCAFFOLD_CONNECTORS
    assert "files" in _SCAFFOLD_CONNECTORS
