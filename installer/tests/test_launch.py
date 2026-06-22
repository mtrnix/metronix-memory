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
    """compose_pull uses _pull_with_progress; compose_up uses subprocess.run."""
    runner = FakeRunner([CommandResult(0, "", "")])
    sh = DockerShell(runner=runner)
    # Pre-seed compose detection so subprocess.run mock isn't polluted
    sh._compose_prefix = ["docker", "compose"]

    pull_envs = []

    def _mock_pull(argv, env):
        pull_envs.append(env or {})
        return 0, ""

    def _mock_run(argv, *, env=None, stdout=None, stderr=None, text=None, **kwargs):
        pull_envs.append(env or {})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("metatron_installer.docker._pull_with_progress", _mock_pull), \
         patch("subprocess.run", _mock_run):
        ok = launch_stack(
            sh,
            compose_file="install/docker-compose.yml",
            compose_profiles="full",
            registry_login=None,
        )
    # launch_stack returns (ok: bool, err: str)
    assert ok == (True, "")
    # compose_pull + compose_up each called with COMPOSE_PROFILES
    assert len(pull_envs) >= 2
    for e in pull_envs:
        assert e["COMPOSE_PROFILES"] == "full"
