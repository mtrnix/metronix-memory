---
space: DPLAT
slug: 06-connector-config-api
title: "Connector Configuration API — Reference"
parent_slug: 02-connector-framework-overview
labels:
  - module:connector-framework
  - doc-type:api-spec
  - role:workspace-admin
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-10T11:00:00Z
version: 5
status: current
linked_jira:
  - DPLAT-001
  - DPLAT-003
---

# Connector Configuration API — Reference

## Overview

The Connector Configuration API enables workspace administrators to programmatically provision, update, and manage connector instances within their tenant. This API supports both initial connector creation and dynamic reconfiguration without service interruption.

## Authentication & Authorization

| Requirement | Value |
|-------------|-------|
| Authentication | OAuth 2.0 Bearer Token |
| Required Role | `workspace-admin` |
| Scope | `connectors:write` |

## API Endpoints

### Create Connector

```
POST /api/v1/connectors
```

Creates a new connector instance with the specified configuration.

**Request Schema:**

```json
{
  "name": "Salesforce Production",
  "type": "salesforce",
  "data_source": {
    "instance_url": "https://myorg.salesforce.com",
    "api_version": "v58.0"
  },
  "sync_schedule": "0 */30 * * *",
  "retention_days": 90,
  "pii_handling": {
    "masking_enabled": true,
    "excluded_fields": ["SSN", "credit_card"]
  },
  "tags": ["production", "sales"]
}
```

**Response:** `201 Created` with connector object including `id`, `status`, and `created_at`.

### Update Connector Configuration

```
PUT /api/v1/connectors/{id}/config
```

Updates an existing connector's configuration. Supports partial updates.

**Request Schema:**

```json
{
  "sync_schedule": "0 */15 * * *",
  "retention_days": 120,
  "data_source": {
    "api_version": "v59.0"
  }
}
```

**Response:** `200 OK` with updated connector object.

## Error Responses

| HTTP Status | Error Code | Description |
|-------------|------------|-------------|
| 400 | `INVALID_CONFIG` | Request body validation failed |
| 401 | `UNAUTHORIZED` | Missing or invalid authentication token |
| 403 | `FORBIDDEN` | User lacks `workspace-admin` role |
| 404 | `CONNECTOR_NOT_FOUND` | Specified connector ID does not exist |
| 409 | `CONFLICT` | Connector name already exists in workspace |
| 429 | `RATE_LIMITED` | Rate limit exceeded |
| 500 | `INTERNAL_ERROR` | Server-side failure |

## Rate Limits

| Tier | Requests/Minute | Burst |
|------|-----------------|-------|
| Standard | 60 | 100 |
| Enterprise | 300 | 500 |

Rate limit headers included in responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining in window
- `X-RateLimit-Reset`: Unix timestamp for window reset

## Environment Variables

The following environment variables control connector API behavior:

| Variable | Description | Default |
|----------|-------------|---------|
| `CONNECTOR_API_ENABLED` | Enable/disable connector API | `true` |
| `CONNECTOR_API_RATE_LIMIT` | Custom rate limit (requests/min) | `60` |
| `CONNECTOR_CONFIG_MAX_SIZE` | Maximum request body size (bytes) | `1048576` |

## Best Practices

- **Idempotency**: Include `Idempotency-Key` header for retry safety
- **Validation**: Validate connector type capabilities before creation
- **Audit Trail**: All configuration changes are recorded in the audit log with timestamp, actor, and diff
- **PII Compliance**: Ensure `pii_handling.masking_enabled` is set appropriately for your compliance officer's requirements
- **Retention Policies**: Retention settings apply to synced data; deleted data is purged after the specified period