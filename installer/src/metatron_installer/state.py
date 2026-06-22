from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class InstallAction(StrEnum):
    INSTALL = "install"
    RECONFIGURE = "reconfigure"
    RESTART = "restart"
    UPGRADE = "upgrade"
    UNINSTALL = "uninstall"


@dataclass(frozen=True)
class InstallState:
    is_fresh: bool
    has_env: bool
    has_running: bool


def detect_existing_install(
    env_path: str | Path, running_containers: list[str]
) -> InstallState:
    has_env = Path(env_path).exists()
    running = [c for c in running_containers if c.startswith("metatron-full-")]
    has_running = len(running) > 0
    return InstallState(
        is_fresh=not (has_env or has_running),
        has_env=has_env,
        has_running=has_running,
    )
