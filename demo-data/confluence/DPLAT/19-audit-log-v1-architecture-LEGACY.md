---
space: DPLAT
slug: 19-audit-log-v1-architecture-LEGACY
title: "Audit Log v1 Architecture (Legacy)"
parent_slug: 03-compliance-vault-overview
labels:
  - module:compliance-vault
  - feature:F-B2
  - doc-type:design
  - superseded
author: ariel@mtrnix.example
created: 2024-03-22T08:00:00Z
updated: 2024-06-10T10:00:00Z
version: 2
status: superseded
linked_jira: []
---

# Audit Log v1 Architecture (Legacy)

## Overview

The audit logging system provides immutable records of all data access and modification events across DPLAT. This document describes the v1 architecture, which establishes the foundation for compliance reporting, forensic analysis, and retention management.

## System Architecture

### High-Level Design

The audit logging system operates as an append-only event capture mechanism. Every connector, data pipeline, and user action generates audit events that flow into a central PostgreSQL database. The architecture prioritizes simplicity, reliability, and query performance.

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Connectors│    │   API Layer │    │  Query UI   │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ▼
                  ┌─────────────┐
                  │ audit_events│
                  │   (Postgres)│
                  └─────────────┘
```

### Database Schema

The system uses a single table, `audit_events`, as the source of truth for all audit data:

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key, auto-incrementing |
| `timestamp` | TIMESTAMPTZ | Event occurrence time |
| `event_type` | VARCHAR(64) | Category of event |
| `actor_id` | VARCHAR(256) | User or service that triggered event |
| `actor_type` | VARCHAR(32) | User, connector, system |
| `tenant_id` | VARCHAR(256) | Target tenant |
| `resource_type` | VARCHAR(64) | Affected resource category |
| `resource_id` | VARCHAR(256) | Affected resource identifier |
| `action` | VARCHAR(32) | CRUD operation |
| `metadata` | JSONB | Event-specific details |
| `ip_address` | INET | Client IP address |
| `user_agent` | TEXT | HTTP user agent string |

## API Interface

### Event Ingestion

The audit log exposes a simple INSERT-only API:

```http
POST /api/v1/audit/events
Content-Type: application/json

{
  "event_type": "data.access",
  "actor_id": "user:12345",
  "actor_type": "user",
  "tenant_id": "tenant:abc",
  "resource_type": "dataset",
  "resource_id": "dataset:789",
  "action": "read",
  "metadata": {
    "query_rows": 15000,
    "pii_fields_accessed": ["email", "ssn"]
  }
}
```

### Event Querying

Workspace admins and compliance officers can query audit events:

```http
GET /api/v1/audit/events?tenant_id={id}&from={timestamp}&to={timestamp}
```

## Operational Considerations

### Retention Policy

The audit log retains all events indefinitely. No automatic deletion or archival occurs. This ensures complete historical records for compliance audits and forensic investigations.

### Performance Characteristics

| Operation | Latency | Notes |
|-----------|---------|-------|
| Event insert | <10ms | Single row insert |
| Query (1000 events) | <200ms | Indexed on timestamp, tenant_id |
| Query (100000 events) | ~2000ms | Pagination recommended |

### Indexing Strategy

The following indexes support common query patterns:

- `idx_events_timestamp` — Chronological queries
- `idx_events_tenant_id` — Per-tenant filtering
- `idx_events_actor_id` — User activity lookups
- `idx_events_event_type` — Event type filtering

## Security Model

### Access Control

| Role | Permissions |
|------|-------------|
| System | INSERT only |
| Workspace admin | READ own tenant |
| Compliance officer | READ all tenants |
| Support | READ with approval |

### PII Handling

The audit log may contain PII in the `metadata` field. All audit data is encrypted at rest using AES-256. In transit, TLS 1.3 is required.

## Event Taxonomy

The system recognizes the following event categories:

- `data.access` — Data read operations
- `data.modify` — Data write operations
- `data.delete` — Data deletion operations
- `auth.login` — Authentication events
- `auth.logout` — Session termination
- `config.change` — Configuration modifications
- `connector.sync` — Connector synchronization events