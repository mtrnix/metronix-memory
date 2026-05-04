# shared-libs

## Overview

This repository contains shared library code used across the Amisol DataPlatform Demo. It provides foundational utilities and helpers that are consumed by multiple modules to ensure consistency and reduce duplication.

The library serves the MOD-A Connector Framework and MOD-B Compliance Vault modules, providing features such as structured logging (F-A1), distributed tracing and telemetry (F-A2), and resilient retry helpers (F-B2).

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `METATRON_LOG_LEVEL` | Logging level for shared library components | `INFO` |
| `AMISOL_DPLAT_TELEMETRY_ENABLED` | Enable/disable telemetry collection | `true` |
| `AMISOL_DPLAT_RETRY_MAX_ATTEMPTS` | Maximum retry attempts for retry helpers | `3` |
| `METATRON_TRACING_ENDPOINT` | OpenTelemetry tracing endpoint | `` |

## Related

- JIRA: DPLAT-REQ-01, DPLAT-REQ-09
- Confluence: DPLAT/06-connector-config-api

## Local development

Run the library in development mode with `npm run dev`, execute tests using `npm test`, and lint code with `npm run lint`.