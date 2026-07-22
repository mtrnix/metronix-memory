#!/usr/bin/env bash
# Metronix web bootstrap installer.
# Publish this file at https://mtrnix.com/install.sh; it downloads a complete
# Metronix release and then delegates to the full installer in that checkout.
set -euo pipefail

REPO_URL="${METRONIX_REPO_URL:-https://github.com/mtrnix/metronix-memory.git}"
INSTALL_DIR="${METRONIX_INSTALL_DIR:-$HOME/.metronix/metronix-memory}"
VERSION="latest"
BRANCH=""
COMMIT=""
UPDATE=false
INSTALL_ARGS=()

if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_RST=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_RST=""
fi
info() { printf '%s\n' "$*"; }
ok()   { printf '%s\xe2\x9c\x93%s %s\n' "$C_OK" "$C_RST" "$*"; }
warn() { printf '%s!%s %s\n' "$C_WARN" "$C_RST" "$*"; }
err()  { printf '%s\xe2\x9c\x97%s %s\n' "$C_ERR" "$C_RST" "$*" >&2; }

usage() {
  cat <<'EOF'
Metronix installer bootstrap

Usage:
  install.sh [bootstrap options] [-- full-installer options]

Bootstrap options:
  --version <latest|tag>  Install the newest release tag (default), or a tag
  --branch <name>         Install a branch instead of a release
  --commit <sha>          Pin the selected version/branch to a commit
  --dir <path>            Managed checkout (default: ~/.metronix/metronix-memory)
  --update                Update an existing managed checkout, then reinstall
  -h, --help              Show this help

All arguments after -- are passed to the full Metronix installer.

Examples:
  curl -fsSL https://mtrnix.com/install.sh | bash
  curl -fsSL https://mtrnix.com/install.sh | bash -s -- -- --mode memory -y
  curl -fsSL https://mtrnix.com/install.sh | bash -s -- --update -- --admin -y
  ./install.sh --version VERSION -- --mode memory
  ./install.sh --branch main -- --mode memory
EOF
}

need_value() {
  [[ $# -ge 2 && -n "$2" ]] || { err "$1 requires a value"; exit 2; }
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version) need_value "$@"; VERSION="$2"; shift 2 ;;
      --branch)  need_value "$@"; BRANCH="$2"; shift 2 ;;
      --commit)  need_value "$@"; COMMIT="$2"; shift 2 ;;
      --dir)     need_value "$@"; INSTALL_DIR="$2"; shift 2 ;;
      --update)  UPDATE=true; shift ;;
      -h|--help) usage; exit 0 ;;
      --) shift; INSTALL_ARGS=("$@"); break ;;
      *) err "Unknown bootstrap option: $1"; info "Put full-installer options after --."; exit 2 ;;
    esac
  done

  if [[ -n "$BRANCH" && "$VERSION" != latest ]]; then
    err "--branch and --version cannot be used together"
    exit 2
  fi
}

check_prereqs() {
  command -v git >/dev/null 2>&1 || {
    err "git is required. Install Git and run this command again."
    exit 1
  }
}

latest_tag() {
  local tag
  tag="$(git -c protocol.file.allow=always ls-remote --refs --tags "$REPO_URL" 2>/dev/null \
    | awk '{sub("refs/tags/", "", $2); print $2}' \
    | sort -V \
    | tail -1)"
  [[ -n "$tag" ]] || {
    err "No release tags were found at $REPO_URL"
    err "Use --branch main only if you intentionally want an unreleased build."
    exit 1
  }
  printf '%s\n' "$tag"
}

selected_ref() {
  if [[ -n "$BRANCH" ]]; then
    printf '%s\n' "$BRANCH"
  elif [[ "$VERSION" == latest ]]; then
    latest_tag
  else
    printf '%s\n' "$VERSION"
  fi
}

validate_existing_checkout() {
  [[ -d "$INSTALL_DIR/.git" ]] || {
    err "$INSTALL_DIR exists but is not a managed Metronix Git checkout."
    err "Choose another location with --dir; no files were changed."
    exit 1
  }

  local origin
  origin="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)"
  [[ "$origin" == "$REPO_URL" ]] || {
    err "$INSTALL_DIR uses an unexpected Git remote: ${origin:-none}"
    err "Expected: $REPO_URL"
    exit 1
  }
}

prepare_checkout() {
  local ref="$1" stash_name="" stash_ref="" backup_dir=""

  # Preserve an interrupted clone rather than deleting an unknown directory.
  if [[ -d "$INSTALL_DIR/.git" ]] \
    && ! git -C "$INSTALL_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
    backup_dir="${INSTALL_DIR}.incomplete-$(date -u +%Y%m%d-%H%M%S)"
    warn "An incomplete checkout was found at $INSTALL_DIR."
    warn "Moving it to $backup_dir before downloading a clean copy."
    mv "$INSTALL_DIR" "$backup_dir"
  fi

  if [[ ! -e "$INSTALL_DIR" ]]; then
    mkdir -p "$(dirname "$INSTALL_DIR")"
    info "Downloading Metronix $ref into $INSTALL_DIR ..."
    git -c protocol.file.allow=always clone --depth 1 --branch "$ref" "$REPO_URL" "$INSTALL_DIR"
  else
    validate_existing_checkout
    if [[ "$UPDATE" != true ]]; then
      warn "Existing installation found; checking out requested release $ref."
      warn "Use --update to make update intent explicit and silence this notice."
    fi

    if [[ -n "$(git -C "$INSTALL_DIR" status --porcelain --untracked-files=all)" ]]; then
      stash_name="metronix-bootstrap-$(date -u +%Y%m%d-%H%M%S)"
      info "Preserving local checkout changes in a temporary Git stash ..."
      git -C "$INSTALL_DIR" stash push --include-untracked -m "$stash_name" >/dev/null
      stash_ref="stash@{0}"
    fi

    info "Fetching Metronix $ref ..."
    git -C "$INSTALL_DIR" fetch --depth 1 origin "refs/tags/$ref:refs/tags/$ref" 2>/dev/null \
      || git -C "$INSTALL_DIR" fetch --depth 1 origin "$ref"

    if git -C "$INSTALL_DIR" show-ref --verify --quiet "refs/tags/$ref"; then
      git -C "$INSTALL_DIR" checkout --detach "$ref" >/dev/null
    else
      git -C "$INSTALL_DIR" checkout -B "$ref" "origin/$ref" >/dev/null
    fi

    if [[ -n "$stash_ref" ]]; then
      info "Restoring preserved local checkout changes ..."
      if git -C "$INSTALL_DIR" stash apply "$stash_ref"; then
        git -C "$INSTALL_DIR" stash drop "$stash_ref" >/dev/null
      else
        err "Metronix was updated, but local changes could not be reapplied cleanly."
        err "They remain safe in Git stash: $stash_name"
        exit 1
      fi
    fi
  fi

  if [[ -n "$COMMIT" ]]; then
    info "Pinning checkout to commit $COMMIT ..."
    if ! git -C "$INSTALL_DIR" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then
      git -C "$INSTALL_DIR" fetch --depth 1 origin "$COMMIT"
    fi
    git -C "$INSTALL_DIR" checkout --detach "$COMMIT" >/dev/null
  fi

  [[ -x "$INSTALL_DIR/install.sh" || -f "$INSTALL_DIR/install.sh" ]] || {
    err "The selected checkout does not contain install.sh"
    exit 1
  }
  ok "Metronix source is ready ($(git -C "$INSTALL_DIR" rev-parse --short HEAD))"
}

run_full_installer() {
  info "Starting the full Metronix installer ..."
  if [[ -r /dev/tty && -w /dev/tty ]]; then
    bash "$INSTALL_DIR/install.sh" "${INSTALL_ARGS[@]}" < /dev/tty
  else
    bash "$INSTALL_DIR/install.sh" "${INSTALL_ARGS[@]}"
  fi
}

main() {
  parse_args "$@"
  check_prereqs
  local ref
  ref="$(selected_ref)"
  prepare_checkout "$ref"
  run_full_installer
}

main "$@"
