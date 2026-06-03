"""create_app must survive optional benchmarker deps failing with non-ImportError.

Regression guard for the uvloop/nest_asyncio2 startup crash: graphrag_llm (a
benchmark-qed transitive dependency) calls ``nest_asyncio2.apply()`` at import
time, which raises ``ValueError`` under uvloop ("Can't patch loop of type
uvloop.Loop"). The optional-module guard in ``create_app`` must swallow ANY
exception from that import, not just ImportError — an optional dev-eval tool
must never take the API down.
"""

from __future__ import annotations

import importlib.abc
import sys

import pytest

from metatron.core.config import Settings


class _ExplodingFinder(importlib.abc.MetaPathFinder):
    """Raises ValueError when the benchmarker api module is imported."""

    target = "metatron.benchmarker.api"

    def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
        if fullname == self.target:
            raise ValueError("Can't patch loop of type <class 'uvloop.Loop'>")
        return None


@pytest.fixture
def exploding_benchmarker(monkeypatch):
    # Purge cached benchmarker modules so the import really goes through the finder.
    # monkeypatch restores the original sys.modules entries on teardown.
    for name in list(sys.modules):
        if name == "metatron.benchmarker.api" or name.startswith("metatron.benchmarker.api."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    finder = _ExplodingFinder()
    sys.meta_path.insert(0, finder)
    yield
    sys.meta_path.remove(finder)


def test_create_app_survives_benchmarker_valueerror(exploding_benchmarker):
    from metatron.api.app import create_app

    app = create_app(Settings(AUTH_ENABLED=False))

    paths = {getattr(r, "path", "") for r in app.routes}
    # App built; benchmarker module routes absent; the rest of the app intact.
    assert not any(p.startswith("/api/v1/benchmarker/") for p in paths)
    assert "/health" in paths
