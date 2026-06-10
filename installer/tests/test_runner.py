import subprocess
import sys

from metatron_installer.config import LlmProvider, Mode, Profile, defaults_for
from metatron_installer.runner import build_overrides, render_artifacts

TEMPLATE = "POSTGRES_PASSWORD=metatron_dev\nFERNET_KEY=\nLLM_PROVIDER=ollama\nNEO4J_PASSWORD=\n"


def test_build_overrides_autogenerates_missing_secrets():
    cfg = defaults_for(Mode.SERVER, Profile.MINIMAL)
    ov = build_overrides(cfg)
    assert len(ov["FERNET_KEY"]) > 0
    assert len(ov["POSTGRES_PASSWORD"]) >= 16
    assert len(ov["NEO4J_PASSWORD"]) >= 16
    assert ov["LLM_PROVIDER"] == "deepseek"


def test_build_overrides_preserves_explicit_secrets():
    cfg = defaults_for(Mode.SERVER, Profile.MINIMAL)
    cfg.fernet_key = "explicit"
    ov = build_overrides(cfg)
    assert ov["FERNET_KEY"] == "explicit"


def test_render_artifacts_sets_compose_profiles_for_full():
    cfg = defaults_for(Mode.LOCAL, Profile.FULL)
    cfg.llm_provider = LlmProvider.OLLAMA
    env_text, compose_profiles = render_artifacts(cfg, template=TEMPLATE)
    assert compose_profiles == "full"
    assert "POSTGRES_PASSWORD=metatron_dev" not in env_text  # got replaced
    assert "COMPOSE_PROFILES=full" in env_text


def test_render_artifacts_minimal_has_empty_profiles():
    cfg = defaults_for(Mode.SERVER, Profile.MINIMAL)
    env_text, compose_profiles = render_artifacts(cfg, template=TEMPLATE)
    assert compose_profiles == ""


def test_cli_dry_run_with_config(tmp_path):
    cfg = tmp_path / "answers.yaml"
    cfg.write_text("mode: server\nprofile: minimal\nllm_provider: deepseek\nllm_api_key: sk-x\n")
    out = subprocess.run(
        [sys.executable, "-m", "metatron_installer", "--config", str(cfg), "--dry-run"],
        capture_output=True,
        text=True,
        cwd="src",
    )
    assert out.returncode == 0
    assert "FERNET_KEY=" in out.stdout
    assert "LLM_PROVIDER=deepseek" in out.stdout
