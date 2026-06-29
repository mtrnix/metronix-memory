#!/bin/bash

# Health check script for Metronix Docker services
# Supports: postgres, qdrant, neo4j, metronix
# Usage: ./docker/healthchecks.sh SERVICE_NAME

set -e

SERVICE="${1}"

# Color codes for output (optional)
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

print_usage() {
    cat << EOF
Health Check Script for Metronix Services

Usage:
    $0 SERVICE_NAME

Supported services:
    postgres    - PostgreSQL database
    qdrant      - Qdrant vector database
    neo4j       - Neo4j graph database
    metronix    - Metronix FastAPI application

Examples:
    $0 postgres
    $0 qdrant
    $0 neo4j
    $0 metronix

EOF
}

# PostgreSQL health check
check_postgres() {
    if command -v pg_isready &> /dev/null; then
        if pg_isready -h localhost -p 5432 -U metronix > /dev/null 2>&1; then
            echo "PostgreSQL is healthy"
            return 0
        else
            echo "PostgreSQL is not ready"
            return 1
        fi
    else
        # Fallback: try to connect with nc
        if timeout 3 nc -w 1 localhost 5432 </dev/null > /dev/null 2>&1; then
            echo "PostgreSQL (port 5432) is responding"
            return 0
        else
            echo "Cannot reach PostgreSQL on port 5432"
            return 1
        fi
    fi
}

# Qdrant health check
check_qdrant() {
    if command -v curl &> /dev/null; then
        response=$(curl -s -w "\n%{http_code}" http://localhost:6333/health 2>/dev/null)
        http_code=$(echo "$response" | tail -n1)
        body=$(echo "$response" | head -n-1)
        
        if [ "$http_code" = "200" ]; then
            echo "Qdrant is healthy: $body"
            return 0
        else
            echo "Qdrant health check failed (HTTP $http_code)"
            return 1
        fi
    else
        # Fallback: just check if port is open
        if timeout 3 nc -w 1 localhost 6333 </dev/null > /dev/null 2>&1; then
            echo "Qdrant (port 6333) is responding"
            return 0
        else
            echo "Cannot reach Qdrant on port 6333"
            return 1
        fi
    fi
}

# Neo4j health check
check_neo4j() {
    # Neo4j uses Bolt protocol on port 7687
    # Simple connectivity check via netcat
    if timeout 3 nc -w 1 localhost 7687 </dev/null > /dev/null 2>&1; then
        echo "Neo4j (port 7687) is responding"
        return 0
    else
        echo "Cannot reach Neo4j on port 7687"
        return 1
    fi
}

# Metronix FastAPI health check
check_metronix() {
    if command -v curl &> /dev/null; then
        response=$(curl -s -w "\n%{http_code}" http://localhost:8000/health 2>/dev/null)
        http_code=$(echo "$response" | tail -n1)
        body=$(echo "$response" | head -n-1)
        
        if [ "$http_code" = "200" ]; then
            echo "Metronix is healthy: $body"
            return 0
        else
            echo "Metronix health check failed (HTTP $http_code)"
            return 1
        fi
    else
        # Fallback: just check if port is open
        if timeout 3 nc -w 1 localhost 8000 </dev/null > /dev/null 2>&1; then
            echo "Metronix (port 8000) is responding"
            return 0
        else
            echo "Cannot reach Metronix on port 8000"
            return 1
        fi
    fi
}

# Main logic
case "${SERVICE}" in
    postgres)
        check_postgres
        ;;
    qdrant)
        check_qdrant
        ;;
    neo4j)
        check_neo4j
        ;;
    metronix)
        check_metronix
        ;;
    --help|-h|help)
        print_usage
        exit 0
        ;;
    "")
        echo "Error: SERVICE_NAME is required"
        print_usage
        exit 1
        ;;
    *)
        echo "Error: Unknown service '${SERVICE}'"
        print_usage
        exit 1
        ;;
esac
