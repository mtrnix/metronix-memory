"""Regression checks for locked dependency security floors."""

from __future__ import annotations

import re
from pathlib import Path


def test_transformers_lock_is_patched_for_cve_2026_4372() -> None:
    """The model loader must not resolve the vulnerable transformers releases."""
    lockfile = Path(__file__).parents[2] / "uv.lock"
    match = re.search(
        r'(?ms)^name = "transformers"\nversion = "([^"]+)"',
        lockfile.read_text(),
    )

    assert match, "transformers is absent from uv.lock"
    assert tuple(map(int, match.group(1).split(".")[:3])) >= (5, 3, 0)
