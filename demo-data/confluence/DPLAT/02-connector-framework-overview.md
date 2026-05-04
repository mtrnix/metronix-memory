---
space: DPLAT
slug: 02-connector-framework-overview
title: "Connector Framework — Module Overview"
parent_slug: 01-product-overview
labels:
  - module:connector-framework
  - doc-type:overview
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-05T10:00:00Z
version: 4
status: current
linked_jira:
  - DPLAT-EPIC-01
  - DPLAT-EPIC-02
  - DPLAT-EPIC-03
---

# Connector Framework — Module Overview

The Connector Framework (MOD-A) provides the foundational plumbing for ingesting data from enterprise systems into the Data Platform. It abstracts authentication, change detection, and payload normalization so that workspace admins can stand up data pipelines without writing custom integrations.

This module focuses on three production-grade connectors and the shared infrastructure that powers them:

| Feature | Description |
|---------|-------------|
| **F-A1** | Salesforce Connector |
| **F-A2** | SAP S/4HANA Connector |
| **F-A3** | Health Monitor |

---

## F-A1: Salesforce Connector

The Salesforce Connector ingests standard and custom objects from Sales Cloud, Service Cloud, and Platform environments. It supports:

- **OAuth 2.0 authentication** via connected apps
- **Change Data Capture (CDC)** for near-real-time event streaming
- **Bulk API v2** for historical backfills
- **Selective field mapping** to reduce PII exposure at the source

Workspace admins configure object subscriptions and field-level mappings through the Connector UI. The connector automatically detects schema changes and surfaces them as warnings in the Health Monitor.

---

## F-A2: SAP S/4HANA Connector

The SAP S/4HANA Connector enables extraction from ERP systems using OData and RFC protocols. Key capabilities:

- **OData v4** for standard CDS views and business objects
- **RFC/IDOC** support for legacy transactional data
- **Delta queues** for incremental extraction
- **Pre-built mappings** for Finance, Sales, and Materials Management modules

This connector requires network-level access to the SAP landscape. Tenant administrators must configure firewall rules and trust relationships before the workspace admin can authenticate.

---

## F-A3: Health Monitor

The Health Monitor provides observability across all active connectors. It tracks:

- **Connection status** (healthy, degraded, disconnected)
- **Sync latency** per data source
- **Error rates** and retry counts
- **Schema drift** notifications

Alerts can be routed to Slack, email, or PagerDuty. Compliance officers can access the audit log to review who modified connector configurations and when.

---

## Configuration Model

Connector configuration is split across two levels:

### Tenant-Level Settings
Managed by tenant administrators:
- Network policies and proxy configuration
- Certificate trusts for TLS termination
- Global rate-limit defaults

### Workspace-Level Settings
Managed by workspace admins:
- Authentication credentials (stored encrypted at rest)
- Object/table subscriptions
- Field-level mappings and transformations
- Sync schedule and frequency

---

## Sync Model

The Connector Framework supports two synchronization modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Real-time (CDC)** | Event-driven streaming via change logs | Customer-facing dashboards, fraud detection |
| **Scheduled (Batch)** | Polling-based extraction on a cron schedule | Historical backfills, nightly ETL |

Both modes produce immutable events in the platform event bus. Downstream consumers subscribe to topics and apply their own transformation logic.

---

## Observability

Each connector emits telemetry to the platform observability stack:

- **Metrics**: records synced, latency percentiles, error counts
- **Logs**: structured JSON logs with correlation IDs
- **Traces**: distributed traces for debugging cross-service issues

Workspace admins can view connector-specific dashboards in the UI. Tenant administrators have access to aggregated metrics across all workspaces.

---

## Access & Governance

### Roles

| Role | Permissions |
|------|-------------|
| Workspace Admin | Configure connectors, view logs, manage subscriptions |
| Compliance Officer | Read-only access to audit logs and PII mappings |
| Tenant Admin | Network and security configuration |

### Audit Logging

All connector configuration changes are recorded in the audit log with:
- User identity and timestamp
- Before/after state (diff)
- Source IP and user agent

---

## Related Documentation

- [Detailed Connector Configuration Guide](#) — step-by-step setup for each connector
- [Retention Policy](#) — data lifecycle rules for synced records
- [API Reference](#) — programmatic access to connector operations