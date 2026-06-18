from types import SimpleNamespace
from unittest.mock import patch

from metatron_installer.docker import CommandResult, DockerShell
from metatron_installer.runner import launch_stack


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append((argv, env))
        return self.results.pop(0)


def test_launch_stack_pulls_then_ups_with_profiles():
    # compose_pull and compose_up use subprocess.run directly (live output),
    # so we mock subprocess.run for those and only use FakeRunner for
    # compose_ps (which uses self._run).
    runner = FakeRunner([CommandResult(0, "", "")])
    sh = DockerShell(runner=runner)

    pull_envs = []

    def _mock_run(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        pull_envs.append(env or {})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", _mock_run):
        ok = launch_stack(
            sh,
            compose_file="install/docker-compose.yml",
            compose_profiles="full",
            registry_login=None,
        )
    # launch_stack returns (ok: bool, err: str)
    assert ok == (True, "")
    # compose_pull and compose_up were each called with COMPOSE_PROFILES
    assert len(pull_envs) >= 2
    for e in pull_envs:
        assert e["COMPOSE_PROFILES"] == "full"
