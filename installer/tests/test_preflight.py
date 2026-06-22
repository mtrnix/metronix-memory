from metatron_installer.preflight import (
    PUBLISHED_PORTS,
    ComposeInfo,
    DockerInfo,
    PortConflict,
    check_compose,
    find_port_conflicts,
    parse_docker_version,
    summarize,
)


def test_summarize_docker_missing_is_not_ok():
    ok, messages = summarize(DockerInfo(present=False), [])
    assert ok is False
    assert any("Docker not available" in m for m in messages)


def test_summarize_docker_present_no_conflicts_is_ok():
    ok, messages = summarize(DockerInfo(present=True, major=27, minor=1), [])
    assert ok is True
    assert any("27.1" in m for m in messages)


def test_summarize_port_conflicts_are_warnings_not_blocking():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [PortConflict(port=8000, service="metatron-api")],
    )
    assert ok is True  # conflicts warn but don't block
    assert any("8000" in m for m in messages)


def test_summarize_compose_missing_is_not_ok():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=False),
    )
    assert ok is False
    assert any("Docker Compose not available" in m for m in messages)


def test_summarize_compose_plugin_detected_is_ok():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=True, kind="plugin", command=("docker", "compose")),
    )
    assert ok is True
    assert any("v2 plugin" in m for m in messages)


def test_summarize_compose_standalone_detected_is_ok():
    ok, messages = summarize(
        DockerInfo(present=True, major=27, minor=1),
        [],
        compose=ComposeInfo(available=True, kind="standalone", command=("docker-compose",)),
    )
    assert ok is True
    assert any("v1 standalone" in m for m in messages)


def test_parse_docker_version_ok():
    info = parse_docker_version("Docker version 27.1.1, build 6312585")
    assert info == DockerInfo(present=True, major=27, minor=1)


def test_parse_docker_version_missing():
    info = parse_docker_version("")
    assert info.present is False


def test_find_port_conflicts_reports_busy_ports():
    busy = {8000, 5433}
    conflicts = find_port_conflicts(checker=lambda p: p in busy)
    ports = {c.port for c in conflicts}
    assert ports == {8000, 5433}


def test_find_port_conflicts_none_when_all_free():
    assert find_port_conflicts(checker=lambda p: False) == []


def test_published_ports_cover_known_services():
    assert 8000 in PUBLISHED_PORTS  # api
    assert 5433 in PUBLISHED_PORTS  # postgres (full-stack offset)
    assert 7688 in PUBLISHED_PORTS  # neo4j bolt


def test_detect_os_returns_known_value():
    from metatron_installer.preflight import detect_os

    assert detect_os() in {"linux", "darwin", "windows"}


# ── check_compose tests (mock subprocess.run) ──


def _fake_run(result_map):
    """Return a mock for subprocess.run that maps argv[0] → result."""
    from types import SimpleNamespace

    def _mock(argv, **kwargs):
        r = result_map.get(argv[0], SimpleNamespace(returncode=1, stdout="", stderr="not found"))
        return r

    return _mock


def test_check_compose_detects_plugin():
    from types import SimpleNamespace
    from unittest.mock import patch

    results = {"docker": SimpleNamespace(returncode=0, stdout="", stderr="")}
    with patch("subprocess.run", _fake_run(results)):
        info = check_compose()
    assert info.available is True
    assert info.kind == "plugin"
    assert info.command == ("docker", "compose")


def test_check_compose_falls_back_to_standalone():
    from types import SimpleNamespace
    from unittest.mock import patch

    results = {
        "docker": SimpleNamespace(returncode=1, stdout="", stderr="unknown command"),
        "docker-compose": SimpleNamespace(returncode=0, stdout="", stderr=""),
    }
    with patch("subprocess.run", _fake_run(results)):
        info = check_compose()
    assert info.available is True
    assert info.kind == "standalone"
    assert info.command == ("docker-compose",)


def test_check_compose_returns_unavailable_when_neither_found():
    from types import SimpleNamespace
    from unittest.mock import patch

    results = {
        "docker": SimpleNamespace(returncode=1, stdout="", stderr="unknown command"),
        "docker-compose": SimpleNamespace(returncode=1, stdout="", stderr="not found"),
    }
    with patch("subprocess.run", _fake_run(results)):
        info = check_compose()
    assert info.available is False


def test_check_compose_handles_file_not_found():
    from unittest.mock import patch

    def _raise_fnf(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    with patch("subprocess.run", _raise_fnf):
        info = check_compose()
    assert info.available is False
