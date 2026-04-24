"""Worker-id builder for the freshness processing-list reclaim pattern.

MTRNIX-316: every ``FreshnessWorker`` instance claims an ephemeral
``worker_id = {hostname}:{pid}:{short-uuid}`` at startup. The id keys the
per-worker processing list (``freshness:{env}:processing:{worker_id}``),
the heartbeat key (``freshness:{env}:heartbeat:{worker_id}``), and the
reclaim lock (``freshness:{env}:reclaim_lock:{worker_id}``).

The id is not persisted to disk — on crash + restart the new worker gets
a fresh id, and the old processing list is discovered + drained by the
reclaim pass.

Test-only hook: ``METATRON_FRESHNESS_TEST_WORKER_ID`` pins the id so
the SIGKILL integration test can assert on a deterministic key.
Setting this variable in production is safe but unnecessary — the default
composition already gives uniqueness per restart.
"""

from __future__ import annotations

import os
import socket
import uuid


def build_worker_id() -> str:
    """Return a fresh worker id.

    Respects the ``METATRON_FRESHNESS_TEST_WORKER_ID`` env override when
    set to a non-empty value; otherwise composes
    ``{hostname}:{pid}:{uuid4_prefix}``.
    """
    override = os.environ.get("METATRON_FRESHNESS_TEST_WORKER_ID")
    if override:
        return override
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


__all__ = ["build_worker_id"]
