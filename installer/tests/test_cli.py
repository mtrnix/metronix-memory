from metatron_installer.cli import _compose_profiles_from_env


def test_compose_profiles_read_from_written_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=1\nCOMPOSE_PROFILES=full\nBAR=2\n")
    assert _compose_profiles_from_env(env, {}) == "full"


def test_compose_profiles_empty_when_absent(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=1\n")
    assert _compose_profiles_from_env(env, {}) == ""


def test_compose_profiles_falls_back_to_process_env(tmp_path):
    missing = tmp_path / ".env"  # not created
    assert _compose_profiles_from_env(missing, {"COMPOSE_PROFILES": "ollama"}) == "ollama"
