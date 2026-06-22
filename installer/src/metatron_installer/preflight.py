from __future__ import annotations

import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Host ports published by install/docker-compose.yml -> service.
PUBLISHED_PORTS: dict[int, str] = {
    5433: "postgres",
    6335: "qdrant",
    6336: "qdrant-grpc",
    7475: "neo4j-http",
    7688: "neo4j-bolt",
    8000: "metatron-api",
    8001: "embedding-proxy",
    8080: "splade",
    6379: "redis",
    3000: "metatron-ui",
    3001: "metatron-ui-cc",
    3080: "open-webui",
    11435: "ollama",
}

_VERSION_RE = re.compile(r"(?:Docker version )?(?P<major>\d+)\.(?P<minor>\d+)")


@dataclass(frozen=True)
class DockerInfo:
    present: bool
    major: int = 0
    minor: int = 0


@dataclass(frozen=True)
class ComposeInfo:
    """Result of probing for Docker Compose availability.

    ``kind`` is ``"plugin"`` (``docker compose`` v2), ``"standalone"``
    (``docker-compose`` v1), or ``""`` when neither is found.
    ``command`` is the argv prefix to use (e.g. ``["docker", "compose"]``).
    """

    available: bool
    kind: str = ""
    command: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortConflict:
    port: int
    service: str


@dataclass(frozen=True)
class DiskInfo:
    free_gb: float
    total_gb: float


# Minimum free disk space required (GB). Below this, install is blocked.
_MIN_DISK_GB = 5.0
# Free space below this triggers a warning (GB).
_WARN_DISK_GB = 10.0


def check_disk_space(path: str = ".") -> DiskInfo:
    """Return free and total disk space in GB for *path* (default: cwd)."""
    usage = shutil.disk_usage(path)
    return DiskInfo(
        free_gb=usage.free / (1024**3),
        total_gb=usage.total / (1024**3),
    )


def detect_os() -> str:
    return platform.system().lower()  # "linux" | "darwin" | "windows"


def parse_docker_version(output: str) -> DockerInfo:
    m = _VERSION_RE.search(output or "")
    if not m:
        return DockerInfo(present=False)
    return DockerInfo(present=True, major=int(m["major"]), minor=int(m["minor"]))


def check_compose() -> ComposeInfo:
    """Detect which Docker Compose variant is available.

    Tries ``docker compose`` (v2 plugin) first, then ``docker-compose`` (v1 standalone).
    Returns ComposeInfo with available=False if neither is found.
    """
    # Try Compose v2 plugin: `docker compose version`
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            return ComposeInfo(available=True, variant="plugin")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try Compose v1 standalone: `docker-compose --version`
    try:
        proc = subprocess.run(
            ["docker-compose", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            return ComposeInfo(available=True, variant="standalone")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return ComposeInfo(available=False)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def find_port_conflicts(
    checker: Callable[[int], bool] = _port_in_use,
) -> list[PortConflict]:
    return [PortConflict(port=p, service=svc) for p, svc in PUBLISHED_PORTS.items() if checker(p)]


def check_compose() -> ComposeInfo:
    """Detect whether ``docker compose`` (v2 plugin) or ``docker-compose``
    (v1 standalone) is available.

    Returns :class:`ComposeInfo` with the detected command prefix, or
    ``available=False`` when neither is found.
    """
    import subprocess

    # Try v2 plugin: `docker compose version`
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return ComposeInfo(available=True, kind="plugin", command=("docker", "compose"))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try v1 standalone: `docker-compose version`
    try:
        r = subprocess.run(
            ["docker-compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return ComposeInfo(available=True, kind="standalone", command=("docker-compose",))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return ComposeInfo(available=False)


def summarize(
    docker: DockerInfo,
    conflicts: list[PortConflict],
    disk: DiskInfo | None = None,
    compose: ComposeInfo | None = None,
) -> tuple[bool, list[str]]:
    """Turn preflight probes into a go/no-go decision plus human-readable lines.

    A missing/unreachable Docker is a hard stop (ok=False). Port conflicts are
    warnings only — the operator may have intentionally remapped or be re-running.
    Insufficient disk space (< MIN_DISK_GB) is also a hard stop. Missing Docker
    Compose (neither v2 plugin nor v1 standalone) is a hard stop.
    """
    messages: list[str] = []
    ok = True
    if docker.present:
        messages.append(f"Docker {docker.major}.{docker.minor} detected")
    else:
        ok = False
        messages.append(
            "Docker not available — is it installed and running? "
            "Start Docker Desktop, or `sudo systemctl start docker`."
        )
    if compose is not None:
        if compose.available:
            label = "v2 plugin" if compose.kind == "plugin" else "v1 standalone"
            messages.append(f"Docker Compose {label} detected")
        else:
            ok = False
            messages.append(
                "Docker Compose not available — install it:\n"
                "  macOS:  brew install docker-compose && "
                "mkdir -p ~/.docker/cli-plugins && "
                "ln -sfn $(brew --prefix)/opt/docker-compose/bin/docker-compose "
                "~/.docker/cli-plugins/docker-compose\n"
                "  Linux:  sudo apt-get install docker-compose-plugin  "
                "(or: sudo yum install docker-compose-plugin)"
            )
    if disk is not None:
        free = disk.free_gb
        if free < _MIN_DISK_GB:
            ok = False
            messages.append(
                f"Disk space critical: {free:.1f} GB free of {disk.total_gb:.0f} GB. "
                f"Need at least {_MIN_DISK_GB:.0f} GB. Free up space and re-run."
            )
        elif free < _WARN_DISK_GB:
            messages.append(
                f"Disk space low: {free:.1f} GB free of {disk.total_gb:.0f} GB. "
                "Full install with ollama may not fit. Consider a minimal profile."
            )
        else:
            messages.append(f"Disk space: {free:.1f} GB free of {disk.total_gb:.0f} GB")
    for c in sorted(conflicts, key=lambda c: c.port):
        messages.append(
            f"Port {c.port} (for {c.service}) is already in use — "
            "free it or change the host mapping in install/docker-compose.yml."
        )
    return ok, messages
