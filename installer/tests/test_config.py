from metatron_installer.config import (
    LlmProvider,
    Mode,
    Profile,
    defaults_for,
)


def test_defaults_server_minimal():
    cfg = defaults_for(Mode.SERVER, Profile.MINIMAL)
    assert cfg.bind_host == "0.0.0.0"
    assert cfg.mode is Mode.SERVER
    assert cfg.profile is Profile.MINIMAL
    assert cfg.llm_provider is LlmProvider.DEEPSEEK


def test_defaults_local_binds_loopback():
    cfg = defaults_for(Mode.LOCAL, Profile.FULL)
    assert cfg.bind_host == "127.0.0.1"


def test_config_is_serializable_to_dict():
    cfg = defaults_for(Mode.LOCAL, Profile.MINIMAL)
    d = cfg.to_dict()
    assert d["mode"] == "local"
    assert d["profile"] == "minimal"
    assert d["llm_provider"] == "deepseek"
