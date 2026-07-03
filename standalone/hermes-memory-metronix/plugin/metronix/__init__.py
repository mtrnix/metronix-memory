"""Standalone Hermes memory-provider scaffold for Metronix.

Designed to be installed into ``~/.hermes/plugins/metronix``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from agent.memory_provider import MemoryProvider

from .client import MetronixClient

logger = logging.getLogger(__name__)


def _get_hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home()
    except Exception:
        return Path.home() / ".hermes"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class MetronixMemoryProvider(MemoryProvider):
    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._client: MetronixClient | None = None
        self._session_id = ""
        self._agent_id = "hermes"
        self._warning_callback = None
        self._status_callback = None

    @property
    def name(self) -> str:
        return "metronix"

    def is_available(self) -> bool:
        cfg = self._load_config()
        has_auth = bool(cfg.get("auth_token") or (cfg.get("email") and cfg.get("password")))
        return bool(cfg.get("base_url") and cfg.get("workspace_id") and has_auth)

    def save_config(self, values, hermes_home):
        path = Path(hermes_home) / "metronix.json"
        existing = _read_json(path)
        existing.update(values)
        _write_json(path, existing)

    def get_config_schema(self):
        return [
            {"key": "base_url", "description": "Metronix base URL", "required": True},
            {"key": "workspace_id", "description": "Metronix workspace id", "required": True},
            {"key": "auth_token", "description": "Metronix bearer token", "secret": True, "env_var": "METRONIX_AUTH_TOKEN"},
            {"key": "email", "description": "Metronix login email"},
            {"key": "password", "description": "Metronix login password", "secret": True, "env_var": "METRONIX_PASSWORD"},
            {"key": "agent_id", "description": "Stable Hermes agent id", "default": "hermes"},
            {"key": "prefetch", "description": "Enable Metronix prefetch injection", "default": True},
            {"key": "prefetch_top_k", "description": "Top K prefetched memories", "default": 8},
            {"key": "prefetch_types", "description": "Kinds to inject: fact, preference, pinned", "default": ["fact", "preference", "pinned"]},
            {"key": "cite_sources", "description": "Include record ids in injected context", "default": True},
            {"key": "write_through", "description": "Mirror Hermes memory writes into Metronix", "default": True},
            {"key": "write_scope", "description": "per_agent, workspace, shared, or session", "default": "workspace"},
            {"key": "sync_turns", "description": "Persist completed turns as session memory", "default": True},
            {"key": "timeout_seconds", "description": "REST timeout in seconds", "default": 20},
        ]

    def initialize(self, session_id: str, **kwargs) -> None:
        self._config = self._load_config()
        self._session_id = session_id
        self._warning_callback = kwargs.get("warning_callback")
        self._status_callback = kwargs.get("status_callback")
        configured_agent_id = str(self._config.get("agent_id") or "").strip()
        self._agent_id = (
            configured_agent_id
            if configured_agent_id and configured_agent_id != "hermes"
            else ""
        ) or (
            str(kwargs.get("agent_identity") or "").strip()
            or "hermes"
        )
        self._client = MetronixClient(
            base_url=str(self._config.get("base_url", "")).strip(),
            workspace_id=str(self._config.get("workspace_id", "")).strip(),
            auth_token=str(self._config.get("auth_token", "")).strip(),
            email=str(self._config.get("email", "")).strip(),
            password=str(self._config.get("password", "")).strip(),
            timeout=float(self._config.get("timeout_seconds", 20) or 20),
        )
        if self._status_callback:
            try:
                self._status_callback("Metronix memory provider initialized")
            except Exception:
                pass

    def system_prompt_block(self) -> str:
        return (
            "# Metronix Memory\n"
            "Active. Relevant Metronix memory may be injected before each turn. "
            "Treat it as background context, not as new user input."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._client or not self._config.get("prefetch", True):
            return ""
        try:
            agent_filter = self._agent_id if self._read_scope() == "per_agent" else None
            results = self._client.search_memory(
                query=query,
                top_k=int(self._config.get("prefetch_top_k", 8) or 8),
                agent_id=agent_filter,
            )
            kinds = {str(k).strip().lower() for k in self._config.get("prefetch_types", []) or []}
            filtered = [r for r in results if self._keep_prefetch_result(r, kinds)]
            return self._format_prefetch(filtered)
        except Exception as exc:
            self._warn(f"Metronix prefetch failed: {exc}")
            return ""

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages=None,
    ) -> None:
        if not self._client or not self._config.get("sync_turns", True):
            return
        target_session_id = session_id or self._session_id

        def _sync() -> None:
            try:
                if user_content.strip():
                    self._client.create_memory(
                        content=user_content.strip(),
                        agent_id=self._agent_id,
                        scope="session",
                        kind="fact",
                        source_type="hermes_turn_user",
                        session_id=target_session_id,
                        metadata={"session_id": target_session_id, "role": "user"},
                    )
                if assistant_content.strip():
                    self._client.create_memory(
                        content=assistant_content.strip(),
                        agent_id=self._agent_id,
                        scope="session",
                        kind="fact",
                        source_type="hermes_turn_assistant",
                        session_id=target_session_id,
                        metadata={"session_id": target_session_id, "role": "assistant"},
                    )
            except Exception as exc:
                self._warn(f"Metronix turn sync failed: {exc}")

        threading.Thread(target=_sync, daemon=True, name="metronix-sync-turn").start()

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if action != "add" or not content or not self._client:
            return
        if not self._config.get("write_through", True):
            return

        def _write() -> None:
            try:
                self._client.create_memory(
                    content=content.strip(),
                    agent_id=self._agent_id,
                    scope=self._map_write_scope(self._config.get("write_scope", "workspace")),
                    kind=self._infer_kind(target, metadata),
                    source_type="hermes_memory_write",
                    tags=["hermes", target],
                    metadata={"target": target, **(metadata or {})},
                )
            except Exception as exc:
                self._warn(f"Metronix write-through failed: {exc}")

        threading.Thread(target=_write, daemon=True, name="metronix-memory-write").start()

    def get_tool_schemas(self):
        return []

    def shutdown(self) -> None:
        return None

    def _load_config(self) -> dict[str, Any]:
        home = _get_hermes_home()
        file_cfg = _read_json(home / "metronix.json")
        merged: dict[str, Any] = {
            "base_url": os.environ.get("METRONIX_BASE_URL", ""),
            "workspace_id": os.environ.get("METRONIX_WORKSPACE_ID", ""),
            "auth_token": os.environ.get("METRONIX_AUTH_TOKEN", ""),
            "email": os.environ.get("METRONIX_EMAIL", ""),
            "password": os.environ.get("METRONIX_PASSWORD", ""),
            "agent_id": os.environ.get("METRONIX_AGENT_ID", ""),
            "prefetch": self._env_bool("METRONIX_PREFETCH", True),
            "prefetch_top_k": int(os.environ.get("METRONIX_PREFETCH_TOP_K", "8")),
            "prefetch_types": self._env_list("METRONIX_PREFETCH_TYPES", ["fact", "preference", "pinned"]),
            "cite_sources": self._env_bool("METRONIX_CITE_SOURCES", True),
            "write_through": self._env_bool("METRONIX_WRITE_THROUGH", True),
            "write_scope": os.environ.get("METRONIX_WRITE_SCOPE", "workspace"),
            "sync_turns": self._env_bool("METRONIX_SYNC_TURNS", True),
            "timeout_seconds": float(os.environ.get("METRONIX_TIMEOUT_SECONDS", "20")),
        }
        merged.update(file_cfg)
        return merged

    def _read_scope(self) -> str:
        write_scope = str(self._config.get("write_scope", "workspace")).strip().lower()
        return "per_agent" if write_scope == "per_agent" else "workspace"

    def _keep_prefetch_result(self, result: dict[str, Any], kinds: set[str]) -> bool:
        if not kinds:
            return True
        record = result.get("record") or {}
        kind = str(record.get("kind", "") or "").strip().lower()
        return kind in kinds

    def _format_prefetch(self, results: list[dict[str, Any]]) -> str:
        if not results:
            return ""
        lines = ["<memory-context>", "## Metronix Memory Context"]
        cite = bool(self._config.get("cite_sources", True))
        for item in results:
            record = item.get("record") or {}
            content = str(record.get("content", "") or "").strip()
            if not content:
                continue
            prefix = f"[{record.get('id')}]" if cite and record.get("id") else "-"
            lines.append(f"{prefix} {content}")
        lines.append("</memory-context>")
        return "\n".join(lines) if len(lines) > 3 else ""

    def _map_write_scope(self, scope: Any) -> str:
        normalized = str(scope or "workspace").strip().lower()
        if normalized == "per_agent":
            return "per_agent"
        if normalized == "session":
            return "session"
        return "global"

    def _infer_kind(self, target: str, metadata: dict[str, Any] | None) -> str:
        if target == "user":
            return "preference"
        if metadata and str(metadata.get("kind", "")).strip():
            return str(metadata["kind"]).strip().lower()
        return "fact"

    def _warn(self, message: str) -> None:
        logger.debug(message)
        if self._warning_callback:
            try:
                self._warning_callback(message)
            except Exception:
                pass

    def _env_bool(self, key: str, default: bool) -> bool:
        raw = os.environ.get(key)
        if raw is None:
            return default
        return raw.strip().lower() not in {"0", "false", "no", "off"}

    def _env_list(self, key: str, default: list[str]) -> list[str]:
        raw = os.environ.get(key)
        if not raw:
            return default
        return [part.strip() for part in raw.split(",") if part.strip()]


def register(ctx) -> None:
    ctx.register_memory_provider(MetronixMemoryProvider())
