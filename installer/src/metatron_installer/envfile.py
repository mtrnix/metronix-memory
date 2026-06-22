from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from pathlib import Path

_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=")


def merge_env(template: str, overrides: dict[str, str]) -> str:
    """Replace KEY= lines in place; append keys not present. Comments untouched."""
    remaining = dict(overrides)
    out_lines: list[str] = []
    for line in template.splitlines():
        m = _KEY_RE.match(line)
        if m and m.group("key") in remaining:
            key = m.group("key")
            out_lines.append(f"{key}={remaining.pop(key)}")
        else:
            out_lines.append(line)
    for key, value in remaining.items():
        out_lines.append(f"{key}={value}")
    return "\n".join(out_lines).rstrip("\n") + "\n"


def atomic_write(target: Path, content: str) -> None:
    """Write via temp file + os.replace so an interrupted write never leaves a partial .env.

    On Windows, ``os.replace`` may fail with ``PermissionError`` when the target is
    held open (e.g. by an editor or anti-virus scanner).  The fallback copies the
    content and removes the temp file, which is not atomic but is safe.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        try:
            os.replace(tmp, target)
        except PermissionError:
            shutil.copy2(tmp, target)
            os.unlink(tmp)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
