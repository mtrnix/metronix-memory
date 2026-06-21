#!/usr/bin/env bash
# Example 1: Quick sync and query
# Prerequisites: docker compose up -d, Python 3.12+
# Usage: ./examples/quickstart.sh

set -euo pipefail

echo "=== Metatron Core Quickstart ==="
echo ""

# 1. Health check
echo "1. Checking API health..."
curl -s http://localhost:8000/ready | python3 -m json.tool
echo ""

# 2. If you have a Confluence space configured, sync it
echo "2. To sync a Confluence space, run:"
echo "   curl -s -X POST http://localhost:8000/api/v1/sync/confluence \\"
echo '     -H "Authorization: Bearer $METATRON_API_KEY"'
echo ""

# 3. Search your knowledge base
echo "3. To search, run:"
echo '   curl -s -X POST http://localhost:8000/api/v1/search \'
echo '     -H "Content-Type: application/json" \'
echo '     -H "Authorization: Bearer $METATRON_API_KEY" \'
echo '     -d '"'"'{"query": "what is the Q2 migration status?"}'"'"' | python3 -m json.tool'
echo ""

echo "=== Done ==="
