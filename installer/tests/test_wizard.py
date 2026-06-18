from metatron_installer.config import LlmProvider, Mode, Profile
from metatron_installer.wizard import Prompter, run_wizard


class ScriptedPrompter(Prompter):
    def __init__(self, answers: dict):
        self.a = answers

    def select(self, message, choices, default=None):
        return self.a[message]

    def text(self, message, default=""):
        return self.a.get(message, default)

    def password(self, message):
        return self.a.get(message, "")

    def confirm(self, message, default=False):
        return self.a.get(message, default)

    def checkbox(self, message, choices):
        return self.a.get(message, [])


def test_wizard_builds_server_minimal_deepseek_config():
    answers = {
        "Deployment mode": "server (bind 0.0.0.0, accessible from network)",
        "LLM provider": "deepseek",
        "DeepSeek API key": "sk-x",
        "Deployment profile": "minimal (core + metatron-ui :3000)",
        "Configure optional integrations?": False,
    }
    cfg = run_wizard(ScriptedPrompter(answers))
    assert cfg.mode is Mode.SERVER
    assert cfg.profile is Profile.MINIMAL
    assert cfg.llm_provider is LlmProvider.DEEPSEEK
    assert cfg.llm_api_key == "sk-x"
    assert cfg.bind_host == "0.0.0.0"


def test_wizard_minimal_ollama_prompts_for_external_host():
    answers = {
        "Deployment mode": "local (bind 127.0.0.1, localhost only)",
        "LLM provider": "ollama",
        "Deployment profile": "minimal (core + metatron-ui :3000)",
        "External Ollama host (http://host:11434)": "http://10.0.0.5:11434",
        "Configure optional integrations?": False,
    }
    cfg = run_wizard(ScriptedPrompter(answers))
    assert cfg.ollama_host == "http://10.0.0.5:11434"
