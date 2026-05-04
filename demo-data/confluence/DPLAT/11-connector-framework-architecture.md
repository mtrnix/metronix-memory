---
space: DPLAT
slug: 11-connector-framework-architecture
title: "Connector Framework — Architecture Deep-Dive"
parent_slug: 02-connector-framework-overview
labels:
  - module:connector-framework
  - doc-type:design
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-12T11:00:00Z
version: 6
status: current
linked_jira:
  - DPLAT-EPIC-01
  - DPLAT-001
  - DPLAT-REQ-11
---

# Connector Framework — Architecture Deep-Dive

## Overview

This document describes the internal architecture of the Connector Framework, the core subsystem responsible for integrating external data sources into DPLAT. The framework supports multi-tenant deployments, with each tenant able to configure connectors that pull data from their respective data sources while maintaining strict isolation boundaries.

## Component Diagram

The Connector Framework consists of six primary components:

```
┌─────────────────────────────────────────────────────────────┐
│                    Connector Framework                      │
├──────────────┬──────────────┬──────────────┬───────────────┤
│  Connector   │   Config     │   Worker     │   Secret      │
│  Registry    │   Service    │   Pool       │   Vault       │
├──────────────┼──────────────┼──────────────┼───────────────┤
│   Event      │   Audit      │              │               │
│   Bus        │   Log        │              │               │
└──────────────┴──────────────┴──────────────┴───────────────┘
```

| Component | Responsibility |
|-----------|----------------|
| Connector Registry | Discovers and manages available connector types |
| Config Service | Stores and validates connector configurations |
| Worker Pool | Executes sync jobs with lease-based assignment |
| Secret Vault | Provides secure access to credentials |
| Event Bus | Publishes lifecycle events |
| Audit Log | Records all configuration changes |

## Configuration Lifecycle

Connector configurations progress through four states:

1. **Draft** — Initial creation, not yet validated
2. **Validated** — Schema validation passed (see DPLAT-001 for schema definition)
3. **Active** — Currently executing sync operations
4. **Retired** — Disabled, retained for audit purposes

The workspace admin initiates state transitions via the UI or API. All transitions are recorded in the audit log with timestamp, actor, and change diff.

## Sync Execution Model

The Worker Pool implements a lease-based task assignment model:

- **Scheduler** assigns sync jobs to workers based on connector priority and tenant quota
- **Lease acquisition** ensures exactly-once execution; workers renew leases every 30 seconds
- **Checkpointing** occurs after each successful batch, enabling recovery from worker failure
- **Parallelization** respects the `max_concurrent_streams` setting per connector

Each tenant has an isolated worker pool with configurable resource limits.

## Error & Retry Policy

The framework implements exponential backoff with jitter:

| Attempt | Wait Time |
|---------|-----------|
| 1 | 0s |
| 2 | 5s |
| 3 | 10s |
| 4 | 20s |
| 5 | 40s |

After five failed attempts, the connector enters `FAILED` state and publishes an alert event. Retriable errors include transient network issues, rate limit responses, and temporary authentication failures. Permanent errors (e.g., schema mismatch, invalid credentials) fail immediately without retry.

## Security Model

### TLS Configuration

All connector-to-data-source communication uses TLS 1.3 with mutual authentication. Certificate validation follows DPLAT-REQ-11, which mandates:

- Root CAs from the DPLAT trust store
- Certificate pinning for production connectors
- Automatic certificate rotation with 30-day warning window

### Secrets Management

Connector credentials are never stored in plaintext. The Secret Vault provides:

- Encrypted at rest (AES-256-GCM)
- Per-tenant encryption keys
- Just-in-time decryption with automatic revocation

## Observability Hooks

The framework exposes three observability surfaces:

### Metrics

| Metric | Description |
|--------|-------------|
| `connector_sync_duration` | Time to complete sync |
| `connector_records_synced` | Count of records transferred |
| `connector_error_rate` | Errors per 1000 records |

### Logs

Structured logs include correlation IDs, tenant context, and PII redaction markers. Log retention follows the tenant's data retention policy.

### Traces

Distributed tracing integrates with OpenTelemetry, with spans for:
- Configuration validation
- Secret retrieval
- Each sync batch
- Error handling

## References

- DPLAT-001: Connector Configuration Schema
- DPLAT-REQ-11: TLS Requirements
- DPLAT-EPIC-01: Connector Framework Epic