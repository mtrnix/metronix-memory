from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

_AUTH_MARKERS = ("401", "denied", "unauthorized", "forbidden", "403")


def parse_ps_services(stdout: str) -> list[tuple[str, str]]:
    """Parse `docker compose ps --format json` into [(service, status)].

    Compose emits either a JSON array or newline-delimited JSON objects depending
    on version; handle both. Malformed/empty lines are skipped.
    """
    text = (stdout or "").strip()
    if not text:
        return []
    objects: list[dict]
    try:
        loaded = json.loads(text)
        objects = loaded if isinstance(loaded, list) else [loaded]
    except json.JSONDecodeError:
        objects = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows: list[tuple[str, str]] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        name = obj.get("Service") or obj.get("Name") or "?"
        status = obj.get("Status") or obj.get("State") or "?"
        rows.append((name, status))
    return rows


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _default_runner(argv: list[str], env: dict[str, str] | None = None) -> CommandResult:
    merged = {**os.environ, **env} if env is not None else None
    proc = subprocess.run(argv, capture_output=True, text=True, env=merged)
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


Runner = Callable[[list[str], dict[str, str] | None], CommandResult]


class DockerShell:
    def __init__(self, runner: Runner = _default_runner):
        self._run = runner
        self._last_stderr = ""

    def version(self) -> CommandResult:
        try:
            return self._run(["docker", "version", "--format", "{{.Server.Version}}"], None)
        except FileNotFoundError:
            return CommandResult(127, "", "docker: command not found")

    def login(self, registry: str, user: str, token: str) -> CommandResult:
        # SECURITY: token is on argv (visible in `ps`) — acceptable for a local
        # single-user install. If reused server-side/CI, switch to --password-stdin.
        return self._run(["docker", "login", registry, "-u", user, "-p", token], None)

    def compose_pull(
        self,
        compose_file: str,
        env: dict[str, str],
        registry_login: Callable[[], CommandResult] | None,
    ) -> bool:
        """Pull images with live progress output. Retries once on auth errors."""
        argv = ["docker", "compose", "-f", compose_file, "pull"]

        def _try_pull() -> int:
            proc = subprocess.run(argv, env=env, stdout=None, stderr=subprocess.PIPE, text=True)
            self._last_stderr = proc.stderr
            return proc.returncode

        rc = _try_pull()
        if rc == 0:
            return True
        if registry_login and self._looks_like_auth_error(self._last_stderr):
            login_res = registry_login()
            if login_res.returncode != 0:
                return False
            return _try_pull() == 0
        return False

    def compose_up(self, compose_file: str, env: dict[str, str]) -> CommandResult:
        """Start the stack (`up -d`) with live output, capturing stderr for diagnostics."""
        proc = subprocess.run(
            ["docker", "compose", "-f", compose_file, "up", "-d"],
            env=env, stdout=None, stderr=subprocess.PIPE, text=True,
        )
        return CommandResult(proc.returncode, "", proc.stderr)

    def compose_ps(self, compose_file: str, env: dict[str, str]) -> CommandResult:
        return self._run(
            ["docker", "compose", "-f", compose_file, "ps", "--format", "json"], env
        )

    def compose_restart(self, compose_file: str, env: dict[str, str]) -> CommandResult:
        """Restart the stack with live output, capturing stderr for diagnostics.

        If the project .env is missing, a temporary empty one is created so compose
        can still resolve ``env_file: .env`` references in the service definitions.
        """
        from pathlib import Path

        env_path = Path(compose_file).parent / ".env"
        env_missing = not env_path.exists()
        if env_missing:
            env_path.touch()

        try:
            proc = subprocess.run(
                ["docker", "compose", "-f", compose_file, "restart"],
                env=env, stdout=None, stderr=subprocess.PIPE, text=True,
            )
            return CommandResult(proc.returncode, "", proc.stderr)
        finally:
            if env_missing:
                env_path.unlink(missing_ok=True)

    def compose_down(
        self, compose_file: str, env: dict[str, str], remove_volumes: bool = False
    ) -> CommandResult:
        """Stop and remove the stack with live output, capturing stderr for diagnostics.

        If the project .env is missing (e.g. deleted between install and uninstall),
        a temporary empty one is created so compose can still resolve ``env_file: .env``
        references in the service definitions.
        """
        from pathlib import Path

        env_path = Path(compose_file).parent / ".env"
        env_missing = not env_path.exists()
        if env_missing:
            env_path.touch()

        try:
            argv = ["docker", "compose", "-f", compose_file, "down"]
            if remove_volumes:
                argv.append("--volumes")
            proc = subprocess.run(
                argv, env=env, stdout=None, stderr=subprocess.PIPE, text=True,
            )
            return CommandResult(proc.returncode, "", proc.stderr)
        finally:
            if env_missing:
                env_path.unlink(missing_ok=True)

    def running_container_names(self) -> list[str]:
        res = self._run(["docker", "ps", "--format", "{{.Names}}"], None)
        if res.returncode != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def logs_tail(self, container: str, lines: int = 40) -> CommandResult:
        return self._run(["docker", "logs", "--tail", str(lines), container], None)

    @staticmethod
    def _looks_like_auth_error(stderr: str) -> bool:
        low = (stderr or "").lower()
        return any(marker in low for marker in _AUTH_MARKERS)
