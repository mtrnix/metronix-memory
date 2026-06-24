from __future__ import annotations

import os


def sweep_expired_archives(export_dir: str, max_age_seconds: int, *, now_ts: float) -> int:
    """Delete *.zip files in export_dir older than max_age_seconds. Returns count deleted."""
    if not os.path.isdir(export_dir):
        return 0
    deleted = 0
    for name in os.listdir(export_dir):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(export_dir, name)
        try:
            if now_ts - os.path.getmtime(path) > max_age_seconds:
                os.remove(path)
                deleted += 1
        except OSError:
            continue
    return deleted
