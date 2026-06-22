from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import __version__, ui
from .answers import AnswersError, load_answers_yaml
from .config import InstallerConfig, Mode, Profile, defaults_for
from .docker import CommandResult, DockerShell, parse_ps_services
from .envfile import atomic_write
from .preflight import (
    ComposeInfo,
    DockerInfo,
    check_compose,
    check_disk_space,
    detect_os,
    find_port_conflicts,
    parse_docker_version,
    summarize,
)
from .profiles import ui_urls
from .runner import launch_stack, render_artifacts
from .state import InstallAction, detect_existing_install


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
    from .prompter_questionary import QuestionaryPrompter
    from .wizard import run_wizard

    return run_wizard(QuestionaryPrompter())


def _run_preflight(shell: DockerShell) -> tuple[bool, ComposeInfo | None]:
    """Probe Docker + Compose + ports and print a summary.

    Returns (go_no_go, compose_info). When compose is available, the shell's
    ``_compose_cmd`` is updated to use the detected command prefix.
    """
    ui.info(f"Preflight on {detect_os()}")
    version_res = shell.version()
    docker: DockerInfo = (
        parse_docker_version(version_res.stdout)
        if version_res.returncode == 0
        else DockerInfo(present=False)
    )
    compose = check_compose()
    if compose.available:
        shell._compose_cmd = list(compose.command)
    conflicts = find_port_conflicts()
    disk = check_disk_space()
    ok, messages = summarize(docker, conflicts, disk, compose=compose)
    for line in messages:
        (ui.success if ok and "in use" not in line else ui.warning)(line)
    return ok, compose


def _render_status(shell: DockerShell, compose_file: str, env: dict[str, str]) -> None:
    res = shell.compose_ps(compose_file, env)
    rows = parse_ps_services(res.stdout)
    if rows:
        ui.status_table(rows)


def _choose_action() -> InstallAction:
    """Ask the user what to do with an existing install."""
    from .prompter_questionary import QuestionaryPrompter

    action_labels = {
        InstallAction.RECONFIGURE: "reconfigure (run wizard, rewrite .env, pull & start)",
        InstallAction.RESTART: "restart (restart containers, no pull, keep config)",
        InstallAction.UPGRADE: "upgrade (pull new images, keep current .env)",
        InstallAction.UNINSTALL: "uninstall (stop & remove containers)",
    }
    label_to_action = {label: a for a, label in action_labels.items()}
    prompter = QuestionaryPrompter()
    choice = prompter.select(
        "An existing install was detected. What would you like to do?",
        list(label_to_action.keys()),
    )
    return label_to_action[choice]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return _main_impl(args, parser)
    except KeyboardInterrupt:
        ui.info("Cancelled.")
        return 0
    except AnswersError as exc:
        ui.error(str(exc))
        return 1


def _main_impl(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:

    repo_root = Path(__file__).resolve().parents[3]
    env_path = repo_root / "install" / ".env"
    example_path = repo_root / ".env.example"
    example = example_path.read_text() if example_path.exists() else ""

    # Dry-run never touches Docker: resolve, render from the example, print, exit.
    if args.dry_run:
        cfg = _resolve_config(args)
        env_text, compose_profiles = render_artifacts(cfg, example)
        ui.info(f"COMPOSE_PROFILES={compose_profiles!r}")
        ui.console.print(env_text)
        return 0

    shell = DockerShell()
    compose_file = str(repo_root / "install" / "docker-compose.yml")
    base_env = dict(os.environ)

    if not _run_preflight(shell)[0]:
        ui.error("Preflight failed. Fix the issues above and re-run.")
        return 2

    # Existing-install handling (interactive only; non-interactive always reconfigures).
    state = detect_existing_install(env_path, shell.running_container_names())
    action = InstallAction.INSTALL
    if not state.is_fresh:
        if args.non_interactive or args.config:
            action = InstallAction.RECONFIGURE
            ui.info("Existing install detected — reconfiguring.")
        else:
            action = _choose_action()

    if action is InstallAction.RESTART:
        ui.info("Restarting the stack...")
        res = shell.compose_restart(compose_file, base_env)
        if res.returncode != 0:
            ui.error(f"Restart failed:\n{res.stderr}")
            return 1
        _render_status(shell, compose_file, base_env)
        return 0

    if action is InstallAction.UNINSTALL:
        from .prompter_questionary import QuestionaryPrompter

        prompter = QuestionaryPrompter()
        remove_images = prompter.confirm("Also remove Docker images?", default=False)
        remove_volumes = prompter.confirm(
            "Also delete all data volumes? (irreversible)", default=False
        )
        ui.info("Stopping the stack...")
        res = shell.compose_down(
            compose_file,
            base_env,
            remove_volumes=remove_volumes,
            remove_images=remove_images,
        )
        if res.returncode == 0:
            ui.success("Stack removed.")
        else:
            ui.error(f"Failed to stop stack:\n{res.stderr}")
            return 1

        # Offer to install fresh right away instead of forcing a re-run.
        if prompter.confirm("Install Metronix Core now?", default=True):
            action = InstallAction.INSTALL
            # Fall through to the install path below.
        else:
            return 0

    # UPGRADE keeps the existing .env untouched (just re-pull + recreate).
    # INSTALL / RECONFIGURE (re)render .env first.
    if action in (InstallAction.INSTALL, InstallAction.RECONFIGURE):
        cfg = _resolve_config(args)
        # Reconfigure merges into the existing .env; a fresh install starts from the example.
        use_existing = action is InstallAction.RECONFIGURE and env_path.exists()
        template = env_path.read_text() if use_existing else example
        env_text, _ = render_artifacts(cfg, template)
        atomic_write(env_path, env_text)
        ui.success("Wrote .env")
    else:
        ui.info("Upgrading: re-pulling images and recreating from the existing .env...")

    compose_profiles = _compose_profiles_from_env(env_path, base_env)
    launch_env = dict(base_env)
    launch_env["COMPOSE_PROFILES"] = compose_profiles

    def _login() -> CommandResult:
        import getpass

        ui.info("Registry requires authentication.")
        user = input("GitHub username: ")
        token = getpass.getpass("GitHub token: ")
        return shell.login("ghcr.io", user, token)

    ui.info("Pulling images and starting the stack...")
    ok, err = launch_stack(shell, compose_file, compose_profiles, registry_login=_login)
    if not ok:
        ui.error(
            "Stack failed to start. Check logs:\n"
            f"  {' '.join(shell._compose_cmd)} -f {compose_file} logs"
        )
        if err:
            ui.console.print(f"[dim]{err.strip()}[/dim]")
        return 1
    ui.success("Stack started.")
    urls = ui_urls(compose_profiles)
    if urls:
        ui.info("UI endpoints:")
        for label, url_str in urls:
            ui.console.print(f"  {label}: [link={url_str}]{url_str}[/link]")
    _render_status(shell, compose_file, launch_env)
    return 0


def _compose_profiles_from_env(env_path: Path, base_env: dict[str, str]) -> str:
    """Read COMPOSE_PROFILES from the written .env so launch matches the rendered config."""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("COMPOSE_PROFILES="):
                return line.split("=", 1)[1].strip()
    return base_env.get("COMPOSE_PROFILES", "")
