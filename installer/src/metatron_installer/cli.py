from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__, ui
from .answers import load_answers_yaml
from .config import InstallerConfig, Mode, Profile, defaults_for
from .envfile import atomic_write
from .runner import render_artifacts


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="metatron-installer")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help="Path to a non-interactive answers YAML")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Render artifacts, do not launch Docker")
    return p


def _resolve_config(args: argparse.Namespace) -> InstallerConfig:
    if args.config:
        return load_answers_yaml(args.config)
    if args.non_interactive:
        # No config file but non-interactive: use safe server/minimal defaults.
        return defaults_for(Mode.SERVER, Profile.MINIMAL)
    from .prompter_questionary import QuestionaryPrompter  # Task 12 provides this
    from .wizard import run_wizard
    return run_wizard(QuestionaryPrompter())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]
    template_path = repo_root / ".env.example"
    template = template_path.read_text() if template_path.exists() else ""

    cfg = _resolve_config(args)
    env_text, compose_profiles = render_artifacts(cfg, template)

    if args.dry_run:
        ui.info(f"COMPOSE_PROFILES={compose_profiles!r}")
        ui.console.print(env_text)
        return 0

    atomic_write(repo_root / ".env", env_text)
    ui.success("Wrote .env")
    # Launch wiring (compose pull/up + healthcheck table) is added in Task 12.
    return 0
