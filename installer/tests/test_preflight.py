from metatron_installer.preflight import (
    PUBLISHED_PORTS,
    DockerInfo,
    PortConflict,
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
