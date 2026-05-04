# health-monitor-ui

## Overview

The health-monitor-ui is a React-based frontend application that provides real-time health monitoring and status visualization for the Amisol DataPlatform. It serves as the primary interface for operations teams to track connector status, view system metrics, and receive alerts about platform components.

This repository implements feature **F-A3 (Health Monitoring Dashboard)**, which is part of the **MOD-A Connector Framework** module. The dashboard aggregates health signals from connected systems, displays uptime statistics, and provides drill-down capabilities for investigating connectivity issues across the platform's integration points.

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `REACT_APP_API_URL` | Backend API endpoint for health data | `http://localhost:8080` |
| `REACT_APP_ENV` | Deployment environment (dev/staging/prod) | `development` |
| `REACT_APP_REFRESH_INTERVAL` | Health check polling interval in milliseconds | `5000` |
| `REACT_APP_WS_ENABLED` | Enable WebSocket real-time updates | `true` |
| `REACT_APP_AUTH_ENABLED` | Enable authentication middleware | `false` |

## Related

**JIRA:** DPLAT-EPIC-03, DPLAT-007, DPLAT-008, DPLAT-027, DPLAT-043

**Confluence:** DPLAT/02-connector-framework-overview, DPLAT/15-connector-ops-runbook

## Local development

```bash
# Install dependencies
npm install

# Run development server
npm start

# Run tests
npm test

# Run linter
npm run lint

# Build for production
npm run build
```

The dev server runs on `http://localhost:3000` with hot-reload enabled. For local testing against a mock backend, set `REACT_APP_API_URL=http://localhost:8080` in your `.env` file.