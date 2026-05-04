---
space: DPLAT
slug: 13-audit-log-query-reference
title: "Audit Log — Query Language Reference"
parent_slug: 03-compliance-vault-overview
labels:
  - module:compliance-vault
  - feature:F-B2
  - doc-type:api-spec
  - role:compliance-officer
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-16T11:00:00Z
version: 3
status: current
linked_jira:
  - DPLAT-009
  - DPLAT-010
  - DPLAT-037
---

# Audit Log — Query Language Reference

The Compliance Vault exposes a domain-specific query language (DSL) for filtering and aggregating audit log events. This reference documents the syntax, operators, and capabilities available to compliance officers and workspace administrators.

## Overview

The query DSL supports filtering by event type, timestamp range, actor identity, resource path, and custom metadata. Queries are submitted via the `/api/v1/compliance/audit-query` endpoint or through the Compliance Vault UI.

## Filter Expressions

Filter expressions combine field names, operators, and values using a simple prefix notation.

### Comparison Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `=` | Exact match | `event_type=data_export` |
| `!=` | Not equal | `status!=failed` |
| `>` / `<` | Numeric comparison | `bytes_transferred>1000000` |
| `>=` / `<=` | Inclusive range | `http_status>=400` |
| `~` | Regex match | `user_agent~.*Chrome.*` |
| `IN` | Set membership | `event_type IN (login, logout, data_export)` |

### Logical Operators

Combine multiple filters with `AND`, `OR`, and `NOT`:

```
event_type=data_export AND actor_role=admin AND bytes_transferred>5000000
```

## Time-Range Syntax

The `timestamp` field supports both absolute and relative range queries.

### Absolute Ranges

Use ISO-8601 timestamps with inclusive bounds:

```
timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]
```

### Relative Ranges

Supports common retention-aware shortcuts:

| Syntax | Meaning |
|--------|---------|
| `-7d` | Last 7 days |
| `-30d` | Last 30 days |
| `-90d` | Last 90 days |
| `-1y` | Last year |

Example:

```
timestamp:[NOW-30d TO NOW]
```

## Field Selectors

### Available Fields

| Field | Description | Type |
|-------|-------------|------|
| `event_type` | Action category | string |
| `actor_id` | User or service identifier | string |
| `actor_role` | Role at time of event | string |
| `resource_path` | Target resource path | string |
| `ip_address` | Client IP (redacted to /24) | string |
| `http_status` | Response code | integer |
| `bytes_transferred` | Data volume | integer |
| `connector_id` | Source connector if applicable | string |
| `tenant_id` | Tenant identifier | string |
| `session_id` | Request correlation ID | string |

### Nested Field Access

Access nested properties with dot notation:

```
metadata.source=connector-crm-001
metadata.pii_fields IN (email, ssn, phone)
```

## Aggregations

Apply aggregations to summarize results:

```
AGGREGATE: count BY actor_role
AGGREGATE: SUM(bytes_transferred) BY event_type
AGGREGATE: DISTINCT(actor_id) WHERE event_type=data_export
```

## Examples

### Example 1: Export Activity in Last Month

```
event_type=data_export AND timestamp:[NOW-30d TO NOW]
```

### Example 2: Failed Logins by IP Range

```
event_type=login AND status=failed AND ip_address=10.0.0.*
```

### Example 3: High-Volume Data Transfers

```
bytes_transferred>100000000 AND event_type IN (data_export, data_download)
```

### Example 4: Admin Actions Summary

```
actor_role=admin AGGREGATE: count BY event_type
```

### Example 5: PII Access by Connector

```
metadata.pii_sensitive=true AND connector_id=connector-crm-001 AND timestamp:[2026-02-01T00:00:00Z TO 2026-02-29T23:59:59Z]
```

## Limitations

- Maximum 100,000 events per query
- Regex matches limited to 100-byte patterns
- Aggregations capped at 1,000 distinct groups
- Queries older than tenant retention policy return empty results