#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ──────────────────────────────────────────────
#  1. uv — auto-install if missing (all platforms)
# ──────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# ──────────────────────────────────────────────
#  2. Platform-specific prerequisites
# ──────────────────────────────────────────────
OS="$(uname -s)"

# ── helper: prompt [Y/n], returns 0 for yes ──
_confirm() {
  local prompt="$1"
  local reply
  read -r -p "  ${prompt} [Y/n] " reply
  [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

# ── helper: ensure Homebrew in PATH after fresh install ──
_ensure_brew_path() {
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

# ═══════════════════════════════════════════════
#  macOS — comprehensive prerequisites check
# ═══════════════════════════════════════════════
if [[ "$OS" == "Darwin" ]]; then
  echo ""
  echo "→ Checking prerequisites for macOS..."
  echo ""
  ALL_OK=true

  # --- curl (built-in on macOS, belt-and-suspenders) ---
  if command -v curl >/dev/null 2>&1; then
    echo "  ✓ curl"
  else
    echo "  ✗ curl not found (should be built-in on macOS)"
    ALL_OK=false
  fi

  # --- Homebrew ---
  if command -v brew >/dev/null 2>&1; then
    echo "  ✓ Homebrew"
  else
    echo "  ✗ Homebrew not found"
    if _confirm "Install Homebrew automatically? (asks for sudo once)"; then
      echo "  Installing Homebrew..."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      _ensure_brew_path
      if command -v brew >/dev/null 2>&1; then
        echo "  ✓ Homebrew installed"
      else
        echo "  ✗ Homebrew install failed — install manually: https://brew.sh"
        ALL_OK=false
      fi
    else
      echo "  → Install manually: https://brew.sh"
      ALL_OK=false
    fi
  fi

  # --- Docker CLI ---
  if command -v docker >/dev/null 2>&1; then
    echo "  ✓ Docker CLI"
  else
    echo "  ✗ Docker CLI not found"
    if command -v brew >/dev/null 2>&1; then
      # Docker Desktop 4.x requires macOS 14 (Sonoma) or later.
      # On older macOS we skip brew install and point the user to a
      # compatible version — brew will error with "does not run on
      # macOS versions other than Sonoma" otherwise.
      _DOCKER_MACOS_MIN_MAJOR=14
      _MACOS_MAJOR=$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)
      if [[ -n "$_MACOS_MAJOR" && "$_MACOS_MAJOR" -lt $_DOCKER_MACOS_MIN_MAJOR ]]; then
        echo "  ⚠  macOS $_MACOS_MAJOR detected — Docker Desktop requires $_DOCKER_MACOS_MIN_MAJOR (Sonoma) or later."
        echo "  → Download a compatible version from the release notes:"
        echo "     https://docs.docker.com/desktop/release-notes/"
        echo "  → Or install Colima as a lightweight alternative:"
        echo "     brew install colima docker"
        echo "     colima start"
        ALL_OK=false
      elif _confirm "Install Docker Desktop via Homebrew? (may ask for sudo)"; then
        echo "  Installing Docker Desktop..."
        if brew install --cask docker; then
          if command -v docker >/dev/null 2>&1; then
            echo "  ✓ Docker CLI installed"
          else
            echo "  ✗ Docker installed but CLI not found in PATH — open Docker.app once, then re-run this script"
            ALL_OK=false
          fi
        else
          echo "  ✗ Docker Desktop install failed. See error above."
          echo "  → Install manually: https://www.docker.com/products/docker-desktop/"
          echo "  → Or try Colima: brew install colima docker && colima start"
          ALL_OK=false
        fi
      else
        echo "  → Install manually: https://www.docker.com/products/docker-desktop/"
        ALL_OK=false
      fi
    else
      echo "  → Install manually (Homebrew also missing): https://www.docker.com/products/docker-desktop/"
      ALL_OK=false
    fi
  fi

  # --- Docker daemon reachable (with retry — Docker Desktop may still be starting) ---
  if command -v docker >/dev/null 2>&1; then
    DAEMON_OK=false
    for attempt in 1 2; do
      if docker info >/dev/null 2>&1; then
        DAEMON_OK=true
        break
      fi
      if [[ $attempt -eq 1 ]]; then
        echo "  ⏳ Docker daemon not responding yet, retrying in 3s..."
        sleep 3
      fi
    done
    if $DAEMON_OK; then
      echo "  ✓ Docker daemon reachable"
    else
      echo "  ✗ Docker daemon not reachable"
      echo ""
      echo "  Docker Desktop is installed but not running. To start it:"
      echo "    open -a Docker"
      echo "    Wait for the whale icon to appear in the menu bar."
      echo "    Then re-run: ./install/bootstrap.sh"
      echo ""
      ALL_OK=false
    fi
  fi

  echo ""
  if $ALL_OK; then
    echo "✓ All prerequisites met."
    echo ""
  else
    echo "✗ Fix the issues above and re-run: ./install/bootstrap.sh"
    exit 1
  fi

# ═══════════════════════════════════════════════
#  Linux — Docker availability check
# ═══════════════════════════════════════════════
elif [[ "$OS" == "Linux" ]]; then
  DOCKER_CMD="docker"
  NEED_SUDO_DOCKER=false

  if ! command -v docker >/dev/null 2>&1; then
    echo ""
    echo "Docker is required to run Metronix Core but was not found." >&2
    echo "Install Docker Engine automatically? (will ask for sudo) [Y/n] " >&2
    read -r REPLY
    if [[ -z "$REPLY" ]] || [[ "$REPLY" =~ ^[Yy] ]]; then
      echo "Installing Docker Engine..." >&2
      curl -fsSL https://get.docker.com | sh
      echo "Docker installed. Adding user to docker group..." >&2
      sudo usermod -aG docker "$USER" 2>/dev/null || true
      # In current shell group membership hasn't taken effect — use sudo for now
      NEED_SUDO_DOCKER=true
      DOCKER_CMD="sudo docker"
    else
      echo "Install manually:  curl -fsSL https://get.docker.com | sh" >&2
      exit 1
    fi
  fi

  # --- Daemon reachable check ---
  if ! $DOCKER_CMD info >/dev/null 2>&1; then
    echo "" >&2
    echo "Docker daemon is not reachable." >&2
    if ! systemctl is-active --quiet docker 2>/dev/null; then
      echo "Docker service is not running. Start it:" >&2
      echo "  sudo systemctl start docker" >&2
    fi
    if ! groups "$USER" | grep -q docker 2>/dev/null; then
      echo "User '$USER' may not be in the 'docker' group." >&2
      echo "Run: sudo usermod -aG docker $USER" >&2
      echo "Then log out and back in (or run: newgrp docker)." >&2
    fi
    exit 1
  fi

# ═══════════════════════════════════════════════
#  Other (Windows via Git Bash, etc.)
# ═══════════════════════════════════════════════
else
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required. Download Docker Desktop from:" >&2
    echo "  https://www.docker.com/products/docker-desktop/" >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not reachable. Launch Docker Desktop and re-run." >&2
    exit 1
  fi
fi

# ──────────────────────────────────────────────
#  3. Launch the Python installer
# ──────────────────────────────────────────────
exec uv run --project "$REPO_ROOT/installer" python -m metatron_installer "$@"
