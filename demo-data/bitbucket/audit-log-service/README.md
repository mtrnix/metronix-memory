# audit-log-service

## Overview

The audit-log-service is a core component of the MOD-B Compliance Vault module, implementing feature F-B2 (Audit Log Storage and Retrieval). This service provides centralized logging capabilities for all compliance-critical events across the Amisol DataPlatform, ensuring immutable records of data access, modifications, and administrative actions.

The service handles high-volume ingestion of audit events, provides queryable storage with retention policies, and exposes APIs for retrieving historical audit trails. It integrates with the MOD-A Connector Framework for event sourcing and supports both real-time streaming and batch replay scenarios.

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `AUDIT_LOG_ENABLED` | Enable/disable audit logging | `true` |
| `AUDIT_LOG_LEVEL` | Logging verbosity (DEBUG/INFO/WARN/ERROR) | `INFO` |
| `AUDIT_RETENTION_DAYS` | Number of days to retain audit records | `2555` |
| `AUDIT_STORAGE_BACKEND` | Storage type (postgres/clickhouse) | `postgres` |
| `AUDIT_BATCH_SIZE` | Events per batch for bulk inserts | `1000` |
| `AUDIT_COMPRESSION_ENABLED` | Enable log compression at rest | `true` |

## Related

JIRA: DPLAT-EPIC-05, DPLAT-009, DPLAT-029, DPLAT-036, DPLAT-038

Confluence: DPLAT/13-audit-log-query-reference, DPLAT/24-adr-007-postgres-vs-clickhouse

## Local development

```bash
# Run the service
docker-compose up

# Run tests
pytest tests/

# Run linters
make lint
```