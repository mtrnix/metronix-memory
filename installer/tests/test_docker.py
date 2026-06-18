from types import SimpleNamespace
from unittest.mock import patch

from metatron_installer.docker import CommandResult, DockerShell, parse_ps_services


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append(argv)
        return self.results.pop(0)


# ── tests that use FakeRunner (methods calling self._run) ──

def test_version_invokes_docker_version():
    runner = FakeRunner([CommandResult(0, "Docker version 27.1.1, build x", "")])
    sh = DockerShell(runner=runner)
    out = sh.version()
    assert runner.calls[0] == ["docker", "version", "--format", "{{.Server.Version}}"]
    assert out.returncode == 0


def test_parse_ps_services_ndjson():
    out = (
        '{"Service": "postgres", "Status": "running"}\n'
        '{"Service": "neo4j", "Status": "starting"}\n'
    )
    assert parse_ps_services(out) == [("postgres", "running"), ("neo4j", "starting")]


def test_parse_ps_services_json_array():
    out = '[{"Name": "metatron-full-api", "State": "running"}]'
    assert parse_ps_services(out) == [("metatron-full-api", "running")]


def test_parse_ps_services_empty_and_malformed():
    assert parse_ps_services("") == []
    assert parse_ps_services("not json\n{bad}") == []


def test_running_container_names_parses_lines():
    runner = FakeRunner([CommandResult(0, "metatron-full-api\nmetatron-full-postgres\n", "")])
    sh = DockerShell(runner=runner)
    names = sh.running_container_names()
    assert names == ["metatron-full-api", "metatron-full-postgres"]
    assert runner.calls[0] == ["docker", "ps", "--format", "{{.Names}}"]


def test_running_container_names_empty_on_failure():
    runner = FakeRunner([CommandResult(1, "", "cannot connect to docker daemon")])
    sh = DockerShell(runner=runner)
    assert sh.running_container_names() == []


# ── tests that mock subprocess.run (compose_pull / compose_up / restart / down) ──

def _mock_subprocess_run(returncode=0, stdout="", stderr=""):
    """Create a mock for subprocess.run that captures calls."""

    calls = []

    def _run_mock(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        calls.append({"argv": argv, "env": env})
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return calls, _run_mock


def test_compose_up_passes_detach_and_profiles_env():
    sh = DockerShell()
    calls, run_mock = _mock_subprocess_run()
    with patch("subprocess.run", run_mock):
        sh.compose_up("install/docker-compose.yml", env={"COMPOSE_PROFILES": "full"})
    argv = calls[0]["argv"]
    assert argv[:3] == ["docker", "compose", "-f"]
    assert "up" in argv and "-d" in argv


def test_pull_falls_back_to_login_on_auth_failure():
    """First pull fails with 401 → login succeeds → retry pull succeeds."""
    call_count = [0]

    def _run_sequence(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="denied: 401 Unauthorized",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    runner = FakeRunner([CommandResult(0, "Login Succeeded", "")])
    sh = DockerShell(runner=runner)
    with patch("subprocess.run", _run_sequence):
        ok = sh.compose_pull(
            "install/docker-compose.yml",
            env={},
            registry_login=lambda: sh.login("ghcr.io", "user", "token"),
        )
    assert ok is True
    assert any(c[:2] == ["docker", "login"] for c in runner.calls)


def test_pull_succeeds_anonymously_without_login():
    sh = DockerShell()
    with patch(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""),
    ):
        ok = sh.compose_pull("install/docker-compose.yml", env={}, registry_login=None)
    assert ok is True


def test_compose_restart_argv(tmp_path):
    """compose_restart uses subprocess.run directly; test argv + tmp .env handling."""
    sh = DockerShell()
    compose_file = str(tmp_path / "install" / "docker-compose.yml")
    # Ensure install/ exists so .env touch doesn't fail
    (tmp_path / "install").mkdir()
    calls, run_mock = _mock_subprocess_run()
    with patch("subprocess.run", run_mock):
        sh.compose_restart(compose_file, env={})
    assert calls[0]["argv"] == ["docker", "compose", "-f", compose_file, "restart"]


def test_compose_down_with_and_without_volumes(tmp_path):
    """compose_down uses subprocess.run directly; test argv variations."""
    sh = DockerShell()
    compose_file = str(tmp_path / "install" / "docker-compose.yml")
    (tmp_path / "install").mkdir()
    all_calls = []

    def _run_capture(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        all_calls.append(argv)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    with patch("subprocess.run", _run_capture):
        sh.compose_down(compose_file, env={})
        sh.compose_down(compose_file, env={}, remove_volumes=True)
    assert all_calls[0] == ["docker", "compose", "-f", compose_file, "down"]
    assert all_calls[1][-1] == "--volumes"
