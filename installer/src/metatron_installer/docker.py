from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
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


# Matches docker compose pull output lines like:
#   " embedding-proxy Pulling"
#   " embedding-proxy Pulled"
_PULL_LINE = re.compile(r"^\s*(\S+)\s+(Pulling|Pulled)")


def _pull_with_progress(argv: list[str], env: dict[str, str]) -> tuple[int, str]:
    """Run ``docker compose pull`` with custom progress display.

    Captures stdout, parses "Pulling"/"Pulled" lines, and shows a compact
    per-service status line: ⬇=pulling  ✓=done  ⏳=pending.

    Non-matching lines (BuildKit output on Linux, errors) pass through
    to the terminal as-is.

    Reads stdout as raw bytes and splits on *both* ``\\n`` and ``\\r`` so
    that Docker Desktop on macOS (which emits layer-progress bars via ``\\r``
    without ``\\n``) doesn't block line-based iteration.

    Returns ``(returncode, stderr_text)``.
    """
    proc = subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    services: dict[str, str] = {}
    seen: list[str] = []
    stderr_lines: list[str] = []
    stdout_remainder = b""

    # Read stderr in a background thread so it doesn't block stdout.
    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        for raw_line in proc.stderr:
            stderr_lines.append(raw_line.decode("utf-8", errors="replace").rstrip("\r\n"))

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    # Read stdout in chunks, split on \n and \r (Docker Desktop may use
    # \r without \n for layer-progress bars — universal-newlines mode
    # doesn't handle that).
    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            break
        data = stdout_remainder + chunk
        # Split on both \n and \r; empty segments from consecutive
        # delimiters are harmless (filtered below).
        segments = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
        # The last segment might be incomplete — keep it for next chunk.
        stdout_remainder = segments.pop()

        for seg in segments:
            stripped = seg.decode("utf-8", errors="replace").strip()
            if not stripped:
                continue
            m = _PULL_LINE.match(stripped)
            if m:
                name, action = m.group(1), m.group(2)
                if name not in services:
                    services[name] = "⏳"
                    seen.append(name)
                if action == "Pulling":
                    services[name] = "⬇"
                elif action == "Pulled":
                    services[name] = "✓"

                # Rebuild and print the compact status line.
                parts = [f"{services[n]} {n}" for n in seen]
                sys.stdout.write("\r\033[K" + "  ".join(parts))
                sys.stdout.flush()
            else:
                # Non-matching line (BuildKit output, errors) — print as-is.
                sys.stdout.write(f"\r\033[K{stripped}\n")
                sys.stdout.flush()

    # Flush any remaining partial output (shouldn't normally happen).
    if stdout_remainder:
        stripped = stdout_remainder.decode("utf-8", errors="replace").strip()
        if stripped:
            m = _PULL_LINE.match(stripped)
            if not m:
                sys.stdout.write(f"\r\033[K{stripped}\n")
                sys.stdout.flush()

    proc.wait()
    t.join(timeout=2)
    sys.stdout.write("\n")
    sys.stdout.flush()

    return proc.returncode, "".join(stderr_lines)


class DockerShell:
    def __init__(self, runner: Runner | None = None, compose_cmd: list[str] | None = None):
        self._run = runner or _default_runner
        self._last_stderr = ""
        self._compose_cmd = compose_cmd or ["docker", "compose"]

    def _compose_argv(self, compose_file: str, *sub: str) -> list[str]:
        """Build a compose argv using the detected compose command prefix."""
        return [*self._compose_cmd, "-f", compose_file, *sub]

    def version(self) -> CommandResult:
        try:
            return self._run(["docker", "version", "--format", "{{.Server.Version}}"], None)
        except FileNotFoundError:
            return CommandResult(127, "", "docker: command not found")

    def compose_version(self) -> CommandResult:
        """Probe whether the configured compose command is available."""
        try:
            return self._run([*self._compose_cmd, "version"], None)
        except FileNotFoundError:
            return CommandResult(127, "", f"{' '.join(self._compose_cmd)}: command not found")

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
        """Pull images with live output. Retries once on auth errors."""
        argv = self._compose_argv(compose_file, "pull")

        def _try_pull() -> int:
            sys.stdout.flush()
            rc, stderr_text = _pull_with_progress(argv, env)
            self._last_stderr = stderr_text
            return rc

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
        sys.stdout.flush()
        proc = subprocess.run(
            self._compose_argv(compose_file, "up", "-d"),
            env=env,
            stdout=None,
            stderr=subprocess.PIPE,
            text=True,
        )
        return CommandResult(proc.returncode, "", proc.stderr)

    def compose_ps(self, compose_file: str, env: dict[str, str]) -> CommandResult:
        return self._run(self._compose_argv(compose_file, "ps", "--format", "json"), env)

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
            sys.stdout.flush()
            proc = subprocess.run(
                self._compose_argv(compose_file, "restart"),
                env=env,
                stdout=None,
                stderr=subprocess.PIPE,
                text=True,
            )
            return CommandResult(proc.returncode, "", proc.stderr)
        finally:
            if env_missing:
                env_path.unlink(missing_ok=True)

    def compose_down(
        self,
        compose_file: str,
        env: dict[str, str],
        remove_volumes: bool = False,
        remove_images: bool = False,
    ) -> CommandResult:
        """Stop and remove the stack with live output, capturing stderr for diagnostics.

        By default only containers are stopped and removed. Pass ``remove_images``
        to also delete the pulled images, and ``remove_volumes`` to wipe named
        data volumes (irreversible).

        If the project .env is missing (e.g. deleted between install and
        uninstall), a temporary empty one is created so compose can still
        resolve ``env_file: .env`` references in the service definitions.
        """
        from pathlib import Path

        env_path = Path(compose_file).parent / ".env"
        env_missing = not env_path.exists()
        if env_missing:
            env_path.touch()

        try:
            argv = self._compose_argv(compose_file, "down")
            if remove_images:
                argv.extend(["--rmi", "all"])
            if remove_volumes:
                argv.append("--volumes")
            sys.stdout.flush()
            proc = subprocess.run(
                argv,
                env=env,
                stdout=None,
                stderr=subprocess.PIPE,
                text=True,
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
