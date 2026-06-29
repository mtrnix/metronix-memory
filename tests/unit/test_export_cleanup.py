import os
import time

from metronix.export.cleanup import sweep_expired_archives


def test_sweep_deletes_old_zips(tmp_path):
    old = tmp_path / "old.zip"
    new = tmp_path / "new.zip"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    now = time.time()
    os.utime(old, (now - 10_000, now - 10_000))
    deleted = sweep_expired_archives(str(tmp_path), max_age_seconds=3600, now_ts=now)
    assert deleted == 1
    assert not old.exists() and new.exists()
