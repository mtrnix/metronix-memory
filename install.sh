#!/bin/bash
#
# Metatron Core (MTRNIX) Installer
# 
# Usage: bash install.sh
# Or:    curl https://app.mtrnix.com/install.sh | bash
#
# This script checks for dependencies (Python 3.12+, Docker, Git),
# clones the repository, and starts the Docker Compose stack.
#
# Security note: Always verify the checksum before piping to bash.
# Download: https://github.com/openclaw/metatron/raw/main/.sha256sum
# Verify:   sha256sum -c .sha256sum
#

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

# Configuration
REPO_URL="${REPO_URL:-https://github.com/openclaw/metatron.git}"
INSTALL_DIR="${HOME}/.metatron"

# ============================================================================
# Helper Functions
# ============================================================================

log_info() {
  echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
  echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
  echo -e "${RED}✗${NC} $1" >&2
}

# ============================================================================
# Dependency Checks
# ============================================================================

check_python() {
  local python_cmd python_version major minor
  
  # Try python3 first, then python
  if command -v python3 &> /dev/null; then
    python_cmd="python3"
  elif command -v python &> /dev/null; then
    python_cmd="python"
  else
    log_error "Python not found. Please install Python 3.12 or newer."
    log_error "  Download from: https://www.python.org/downloads/"
    exit 1
  fi
  
  # Get version and parse major.minor
  python_version=$("$python_cmd" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
  major=$(echo "$python_version" | cut -d. -f1)
  minor=$(echo "$python_version" | cut -d. -f2)
  
  # Check version >= 3.12
  if [[ $major -lt 3 ]] || [[ $major -eq 3 && $minor -lt 12 ]]; then
    log_error "Python 3.12+ required, but found Python $python_version"
    log_error "  Download Python 3.12+ from: https://www.python.org/downloads/"
    exit 1
  fi
  
  log_info "Python $python_version detected"
}

check_docker() {
  if ! command -v docker &> /dev/null; then
    log_warning "Docker not found. Installation requires Docker."
    log_warning "  Install from: https://docs.docker.com/get-docker/"
    log_warning "  Without Docker, the installer cannot start services."
    return 1
  fi
  
  if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    log_warning "Docker Compose not found. Installation requires Docker Compose."
    log_warning "  Install from: https://docs.docker.com/compose/install/"
    return 1
  fi
  
  log_info "Docker detected"
}

check_git() {
  if ! command -v git &> /dev/null; then
    log_error "Git not found. Please install Git."
    log_error "  Download from: https://git-scm.com/download/"
    exit 1
  fi
  
  log_info "Git detected"
}

# ============================================================================
# Repository Setup
# ============================================================================

setup_repository() {
  local response
  
  echo ""
  echo "Repository Configuration:"
  echo "  Default: $REPO_URL"
  read -p "  Enter GitHub URL or press Enter for default: " response
  
  if [[ -n "$response" ]]; then
    REPO_URL="$response"
  fi
  
  # Idempotency: remove existing install directory with warning
  if [[ -d "$INSTALL_DIR" ]]; then
    log_warning "Installation directory already exists: $INSTALL_DIR"
    read -p "  Remove and reinstall? (y/n) " response
    if [[ "$response" == "y" || "$response" == "Y" ]]; then
      log_info "Removing existing installation..."
      rm -rf "$INSTALL_DIR"
    else
      log_info "Using existing installation at: $INSTALL_DIR"
      return 0
    fi
  fi
  
  log_info "Cloning repository from: $REPO_URL"
  if ! git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"; then
    log_error "Failed to clone repository"
    log_error "  Check the URL and your internet connection"
    exit 1
  fi
  
  log_info "Repository cloned to: $INSTALL_DIR"
}

# ============================================================================
# Docker Compose Setup
# ============================================================================

setup_docker_compose() {
  cd "$INSTALL_DIR"
  
  # Verify docker-compose.yml exists
  if [[ ! -f docker-compose.yml ]]; then
    log_error "docker-compose.yml not found in $INSTALL_DIR"
    exit 1
  fi
  
  log_info "Found docker-compose.yml"
  
  # Copy .env.example to .env if it doesn't exist
  if [[ -f .env.example && ! -f .env ]]; then
    cp .env.example .env
    log_info "Created .env from .env.example"
    log_warning "Edit .env to add your API tokens (Telegram, Discord, Slack, etc.)"
  fi
  
  # Pull images
  log_info "Pulling Docker images (this may take a minute)..."
  if ! docker-compose pull 2>&1; then
    # Try docker compose (newer version)
    if ! docker compose pull 2>&1; then
      log_error "Failed to pull Docker images"
      log_error "  Ensure Docker daemon is running: docker ps"
      exit 1
    fi
  fi
  
  log_info "Docker images pulled successfully"
  
  # Start services
  log_info "Starting Docker Compose stack..."
  if ! docker-compose up -d 2>&1; then
    # Try docker compose (newer version)
    if ! docker compose up -d 2>&1; then
      log_error "Failed to start Docker Compose stack"
      log_error "  Check Docker logs: docker-compose logs"
      exit 1
    fi
  fi
  
  log_info "Docker Compose stack started"
}

# ============================================================================
# Verification and Next Steps
# ============================================================================

show_success() {
  echo ""
  echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}✓ Metatron installed successfully!${NC}"
  echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
  echo ""
  echo "Next steps:"
  echo "  1. Check service health: docker-compose logs -f"
  echo "  2. Open browser: http://localhost:8000"
  echo "  3. Add configuration tokens to .env (if using bots)"
  echo "  4. See docs/QUICKSTART.md for first steps"
  echo ""
  echo "Logs and troubleshooting:"
  echo "  docker-compose logs metatron       # Application logs"
  echo "  docker-compose logs postgres       # Database logs"
  echo "  docker-compose logs qdrant         # Vector DB logs"
  echo "  docker-compose down                # Stop all services"
  echo ""
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
  echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
  echo -e "${GREEN}Metatron Core (MTRNIX) Installation${NC}"
  echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
  echo ""
  
  # Check all dependencies
  echo "Checking dependencies..."
  check_python
  check_docker || {
    log_warning "Continuing without Docker, but installation will fail at setup step"
  }
  check_git
  echo ""
  
  # Setup repository
  setup_repository
  echo ""
  
  # Setup Docker Compose
  setup_docker_compose
  echo ""
  
  # Show success message
  show_success
}

# Execute main function
main "$@"
