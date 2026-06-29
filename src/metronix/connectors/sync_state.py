"""Track last sync time per source type per workspace.

File-based persistence — simple, no DB dependency. Stores a JSON dict
mapping "workspace_id:source_type" → ISO timestamp string.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

logger = structlog.get_logger()


class SyncState:
    """File-based sync state. Stores last_sync_at per (workspace_id, source_type)."""

    def __init__(self, state_dir: str = ".metronix") -> None:
        self.state_file = Path(state_dir) / "sync_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict[str, str]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("sync_state.load_error", error=str(e))
                return {}
        return {}

    def _save(self) -> None:
        self.state_file.write_text(json.dumps(self._state, indent=2))

    def _key(self, workspace_id: str, source_type: str) -> str:
        return f"{workspace_id}:{source_type}"

    def get_last_sync(self, workspace_id: str, source_type: str) -> datetime | None:
        """Get last successful sync time, or None if never synced."""
        ts = self._state.get(self._key(workspace_id, source_type))
        if ts:
            return datetime.fromisoformat(ts)
        return None

    def set_last_sync(
        self,
        workspace_id: str,
        source_type: str,
        ts: datetime | None = None,
    ) -> None:
        """Record successful sync time. Defaults to now (UTC)."""
        self._state[self._key(workspace_id, source_type)] = (ts or datetime.now(UTC)).isoformat()
        self._save()

    def clear(self, workspace_id: str, source_type: str) -> None:
        """Clear sync state for a source (forces full sync next time)."""
        self._state.pop(self._key(workspace_id, source_type), None)
        self._save()
