import zipfile

from metronix.export.archive import ExportArchiveWriter


def test_archive_writes_entries(tmp_path):
    dest = tmp_path / "sub" / "export.zip"
    with ExportArchiveWriter(str(dest)) as w:
        w.write_text("manifest.json", "{}")
        w.write_text("ws1/memory/a.md", "hello")
    assert dest.exists()
    with zipfile.ZipFile(dest) as z:
        assert set(z.namelist()) == {"manifest.json", "ws1/memory/a.md"}
        assert z.read("ws1/memory/a.md").decode() == "hello"


def test_archive_size_after_close(tmp_path):
    dest = tmp_path / "export.zip"
    w = ExportArchiveWriter(str(dest))
    with w:
        w.write_text("a.txt", "x" * 1000)
    assert w.size_bytes > 0
