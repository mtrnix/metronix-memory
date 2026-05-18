"""Backward-compat re-export shim — BootstrapStateStore moved to workspaces/bootstrap/store.py.

Import from ``metatron.workspaces.bootstrap.store`` or ``metatron.workspaces.bootstrap``
for new code.  This shim exists to avoid breaking any external consumer that pins the
old import path (e.g. enterprise plugins, migration scripts).
"""

from __future__ import annotations

from metatron.workspaces.bootstrap.store import BootstrapStateStore

__all__ = ["BootstrapStateStore"]
