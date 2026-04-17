#!/bin/bash

# =============================================================================
# Metatron Core - Installation Script
# =============================================================================

# Colors
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Repository settings
REPO_URL="https://github.com/mtrnix/metatroncore.git"
REPO_BRANCH="develop"
TEMP_DIR="metatroncore_temp"

# Print header
print_header() {
    echo -e "${PURPLE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║         METATRON CORE INSTALLATION                           ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Print section header
print_section() {
    echo -e "\n${PURPLE}✦ ${CYAN}$1${NC}"
    echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Print success message
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Print error message
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Print info message
print_info() {
    echo -e "${CYAN}→ $1${NC}"
}

# Print warning message
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Generate Fernet key
generate_fernet_key() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32 | tr -d '\n'
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())" 2>/dev/null
    else
        echo "$(date +%s)$RANDOM$RANDOM$RANDOM" | sha256sum | base64 | head -c 43
    fi
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Wait for service to be healthy
wait_for_healthy() {
    local service_name="$1"
    local max_attempts=30
    local attempt=1
    
    print_info "Waiting for $service_name to be healthy..."
    
    while [ $attempt -le $max_attempts ]; do
        local status=$(docker inspect --format='{{.State.Health.Status}}' "$service_name" 2>/dev/null)
        
        if [ "$status" = "healthy" ]; then
            print_success "$service_name is healthy"
            return 0
        elif [ "$status" = "unhealthy" ]; then
            print_error "$service_name is unhealthy"
            return 1
        fi
        
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo ""
    print_warning "$service_name healthcheck timeout"
    return 1
}

# Start Docker Compose with retry
start_docker_compose() {
    local max_retries=2
    local retry=0
    
    print_info "Starting all services..."
    
    while [ $retry -le $max_retries ]; do
        if [ $retry -gt 0 ]; then
            print_info "Retry attempt $retry/$max_retries..."
        fi
        
        # Start services
        if docker compose version >/dev/null 2>&1; then
            docker compose up -d
        else
            docker-compose up -d
        fi
        
        if [ $? -ne 0 ]; then
            print_error "Failed to start services"
            return 1
        fi
        
        # Wait for services to be ready
        sleep 5
        
        # Check critical services
        local all_healthy=true
        
        for service in metatron-full-postgres metatron-full-qdrant metatron-full-neo4j metatron-full-ollama; do
            if ! wait_for_healthy "$service"; then
                all_healthy=false
                break
            fi
        done
        
        if [ "$all_healthy" = true ]; then
            # Give metatron-full-api a bit more time
            print_info "Waiting for API service to initialize..."
            sleep 10
            
            if wait_for_healthy "metatron-full-api"; then
                return 0
            fi
        fi
        
        # If we got here and this is not the last retry, restart
        if [ $retry -lt $max_retries ]; then
            print_warning "Some services failed to start properly, restarting..."
            if docker compose version >/dev/null 2>&1; then
                docker compose restart
            else
                docker-compose restart
            fi
            sleep 5
        fi
        
        retry=$((retry + 1))
    done
    
    return 1
}

# Main installation process
main() {
    clear
    print_header
    
    # Check prerequisites
    print_section "Checking System Requirements"
    
    # Check Docker
    if command_exists docker; then
        print_success "Docker installed"
    else
        print_error "Docker not installed"
        exit 1
    fi
    
    # Check Docker Compose
    if docker compose version >/dev/null 2>&1; then
        print_success "Docker Compose installed"
    elif command_exists docker-compose; then
        print_success "Docker Compose installed"
    else
        print_error "Docker Compose not installed"
        exit 1
    fi
    
    # Check Git
    if command_exists git; then
        print_success "Git installed"
    else
        print_error "Git not installed"
        exit 1
    fi
    
    # Check curl or wget
    if command_exists curl || command_exists wget; then
        print_success "Download tool installed (curl/wget)"
    else
        print_error "curl or wget not installed"
        exit 1
    fi
    
    # GitHub credentials
    print_section "GitHub Authentication"
    print_info "Authenticating to access private repositories"
    
    echo -en "${CYAN}GitHub username: ${NC}"
    read GITHUB_USERNAME
    
    echo -en "${CYAN}GitHub token: ${NC}"
    read -s GITHUB_TOKEN
    echo
    
    # Login to GitHub Container Registry
    print_section "GitHub Container Registry"
    echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USERNAME" --password-stdin > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        print_error "Failed to login to GHCR"
        exit 1
    fi
    print_success "GHCR authentication successful"
    
    # Clone repository (silent mode)
    print_section "Cloning Repository"
    print_info "Cloning repository (branch: $REPO_BRANCH)..."
    
    if [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
    
    git clone --quiet --branch "$REPO_BRANCH" "$REPO_URL" "$TEMP_DIR"
    if [ $? -ne 0 ]; then
        print_error "Failed to clone repository"
        exit 1
    fi
    print_success "Repository cloned successfully"
    
    # Copy configuration files
    print_section "Copying Configuration Files"
    
    if [ -f "$TEMP_DIR/.env.example" ]; then
        cp "$TEMP_DIR/.env.example" .env.example
        print_success ".env.example copied"
    else
        print_error ".env.example not found"
        exit 1
    fi
    
    if [ -f "$TEMP_DIR/install/docker-compose.yml" ]; then
        cp "$TEMP_DIR/install/docker-compose.yml" docker-compose.yml
        print_success "docker-compose.yml copied"
    else
        print_error "docker-compose.yml not found"
        exit 1
    fi
    
    # Cleanup
    print_section "Cleaning Up"
    rm -rf "$TEMP_DIR"
    print_success "Temporary files removed"
    
    # Create .env file
    print_section "Configuring Environment"
    
    if [ -f ".env" ]; then
        print_info "Existing .env file found"
        echo -en "${CYAN}Overwrite? (y/N): ${NC}"
        read OVERWRITE
        if [[ ! $OVERWRITE =~ ^[Yy]$ ]]; then
            print_info "Using existing .env file"
        else
            cp .env.example .env
            print_info "Created new .env from example"
        fi
    else
        cp .env.example .env
        print_info "Created .env from example"
    fi
    
    # Configure .env file
    print_info "Configuring environment variables..."
    
    sed -i "s/^NEO4J_USER=.*/NEO4J_USER=user/" .env
    sed -i "s/^NEO4J_PASSWORD=.*/NEO4J_PASSWORD=pass/" .env
    
    # Generate Fernet key
    print_info "Generating Fernet encryption key..."
    FERNET_KEY=$(generate_fernet_key)
    if [ -z "$FERNET_KEY" ]; then
        print_error "Failed to generate Fernet key"
        exit 1
    fi
    
    if grep -q "^FERNET_KEY=" .env; then
        sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$FERNET_KEY|" .env
    else
        echo "FERNET_KEY=$FERNET_KEY" >> .env
    fi
    print_success "Fernet key generated"
    
    # Configure LLM provider
    if grep -q "^LLM_PROVIDER=" .env; then
        sed -i "s/^LLM_PROVIDER=.*/LLM_PROVIDER=deepseek/" .env
    else
        echo "LLM_PROVIDER=deepseek" >> .env
    fi
    
    # Ask for DeepSeek API key (hidden input)
    print_section "DeepSeek API Configuration"
    echo -en "${CYAN}DeepSeek API key: ${NC}"
    read -s DEEPSEEK_API_KEY
    echo
    
    if grep -q "^DEEPSEEK_API_KEY=" .env; then
        sed -i "s/^DEEPSEEK_API_KEY=.*/DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY/" .env
    else
        echo "DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY" >> .env
    fi
    print_success "DeepSeek API key configured"
    
    # Ask for OpenAI Compat key (hidden input)
    print_section "OpenAI Compatible API Configuration"
    echo -en "${CYAN}OpenAI Compat key (for Open WebUI): ${NC}"
    read -s METATRON_OPENAI_COMPAT_KEY
    echo
    
    if grep -q "^METATRON_OPENAI_COMPAT_KEY=" .env; then
        sed -i "s/^METATRON_OPENAI_COMPAT_KEY=.*/METATRON_OPENAI_COMPAT_KEY=$METATRON_OPENAI_COMPAT_KEY/" .env
    else
        echo "METATRON_OPENAI_COMPAT_KEY=$METATRON_OPENAI_COMPAT_KEY" >> .env
    fi
    print_success "OpenAI Compat key configured"
    
    # Configure optional settings with defaults
    print_section "Optional Configuration"
    
    # Set default values for optional settings
    sed -i "s/^METATRON_OPENAI_COMPAT_ENABLED=.*/METATRON_OPENAI_COMPAT_ENABLED=true/" .env
    sed -i "s/^QUERY_EXPANSION_ENABLED=.*/QUERY_EXPANSION_ENABLED=true/" .env
    
    print_success "OpenAI Compat endpoint enabled (default)"
    print_success "Query expansion enabled (default)"
    
    # Display final configuration
    print_section "Configuration Summary"
    echo -e "${CYAN}Environment:${NC} $(grep METATRON_ENV .env | cut -d= -f2 | sed 's/^[[:space:]]*//' | sed 's/#.*//')"
    echo -e "${CYAN}Database:${NC} PostgreSQL + Neo4j + Qdrant"
    echo -e "${CYAN}LLM Provider:${NC} DeepSeek"
    echo -e "${CYAN}Neo4j User:${NC} user"
    echo -e "${CYAN}OpenAI Compat:${NC} enabled"
    echo -e "${CYAN}Query Expansion:${NC} enabled"
    
    # Start Docker Compose with retry
    print_section "Launching Metatron Core"
    
    if start_docker_compose; then
        print_success "All services started successfully"
    else
        print_error "Failed to start services after multiple attempts"
        print_info "You can try to start manually with: docker compose up -d"
        exit 1
    fi
    
    # Final check
    print_section "Service Status"
    if docker compose version >/dev/null 2>&1; then
        docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
    else
        docker-compose ps
    fi
    
    # Display success message
    echo -e "\n${PURPLE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                                                              ║"
    echo "║     METATRON CORE INSTALLATION COMPLETE                      ║"
    echo "║                                                              ║"
    echo "║  Access your system:                                        ║"
    echo "║                                                              ║"
    echo -e "║  ${GREEN}Web UI:${NC}            http://localhost:3000${PURPLE}                    ║"
    echo -e "║  ${GREEN}API Server:${NC}         http://localhost:8000${PURPLE}                    ║"
    echo -e "║  ${GREEN}Open WebUI:${NC}         http://localhost:3080${PURPLE}                    ║"
    echo "║                                                              ║"
    echo "║  Services:                                                  ║"
    echo -e "║  • PostgreSQL:    ${CYAN}localhost:5433${PURPLE}                              ║"
    echo -e "║  • Qdrant:        ${CYAN}localhost:6335${PURPLE}                              ║"
    echo -e "║  • Neo4j:         ${CYAN}localhost:7688${PURPLE}                              ║"
    echo -e "║  • Ollama:        ${CYAN}localhost:11435${PURPLE}                             ║"
    echo "║                                                              ║"
    echo "║  Commands:                                                 ║"
    echo -e "║  • View logs:    ${CYAN}docker compose logs -f${PURPLE}                        ║"
    echo -e "║  • Stop:         ${CYAN}docker compose down${PURPLE}                           ║"
    echo -e "║  • Restart:      ${CYAN}docker compose restart${PURPLE}                        ║"
    echo "║                                                              ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Run main function
main "$@"
