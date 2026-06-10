from metatron_installer.state import InstallAction, detect_existing_install


def test_no_env_means_fresh_install(tmp_path):
    state = detect_existing_install(env_path=tmp_path / ".env", running_containers=[])
    assert state.is_fresh is True


def test_env_present_is_not_fresh(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    state = detect_existing_install(env_path=env, running_containers=[])
    assert state.is_fresh is False


def test_running_containers_detected(tmp_path):
    state = detect_existing_install(
        env_path=tmp_path / ".env",
        running_containers=["metatron-full-api", "metatron-full-postgres"],
    )
    assert state.is_fresh is False
    assert state.has_running is True


def test_install_action_values():
    assert {a.value for a in InstallAction} >= {
        "reconfigure",
        "restart",
        "upgrade",
        "uninstall",
    }
