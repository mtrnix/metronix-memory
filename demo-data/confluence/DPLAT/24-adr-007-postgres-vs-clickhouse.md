---
space: DPLAT
slug: 24-adr-007-postgres-vs-clickhouse
title: "ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)"
parent_slug: 01-product-overview
labels:
  - doc-type:adr
  - status:accepted
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-03-15T11:00:00Z
version: 2
status: current
linked_jira:
  - DPLAT-EPIC-05
---

# ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)

## Context

The audit log feature records all data access and modification events across connectors, providing compliance officers with a verifiable trail of who accessed what data, when, and from which tenant context. Key requirements:

- **Volume**: Up to 500K events/hour at peak, ~400MB/hour raw
- **Retention**: 12 months hot, then archived per tenant retention policy
- **Query patterns**: Time-range filters, tenant isolation, connector-specific lookups, PII redaction toggles
- **Multi-tenant**: Row-level security per tenant, with workspace admin self-service queries

The audit log must support both operational debugging (recent events, low latency) and compliance reporting (historical aggregations, ad-hoc queries).

## Options Considered

### Postgres (Existing Stack)

| Criterion | Assessment |
|-----------|------------|
| Query flexibility | Full SQL, JOINs, subqueries, window functions |
| Transactions | Native ACID, important for audit integrity |
| Retention management | TTL via pg_cron + partitioning |
| Multi-tenant | Row-level security, native support |
| Operational complexity | Low — existing tooling, monitoring, backups |
| Write throughput | ~50K events/sec single node |
| Compression | TOAST, but limited gains on JSONB |

### ClickHouse

| Criterion | Assessment |
|-----------|------------|
| Query flexibility | OLAP-optimized, limited JOINs, no transactions |
| Transactions | No native ACID; eventual consistency |
| Retention management | Native TTL, automatic data lifecycle |
| Multi-tenant | Requires explicit filtering, no RLS |
| Operational complexity | High — separate cluster, different tooling |
| Write throughput | ~500K events/sec single node |
| Compression | Excellent (3-5x over Postgres) |

### TimescaleDB

| Criterion | Assessment |
|-----------|------------|
| Query flexibility | Full Postgres + time-series optimizations |
| Transactions | Native ACID |
| Retention management | Policy-based chunk retention |
| Multi-tenant | Hypertable-per-tenant or RLS |
| Operational complexity | Medium — extension management, versioning |
| Write throughput | ~100K events/sec single node |
| Compression | Hypertable-native, good gains |

## Decision

**Use Postgres for v2 audit log storage.** ClickHouse will be evaluated for v3 if:

- Single-tenant queries exceed 5 seconds on 6-month data
- Storage costs exceed $0.05/GB/month at scale
- Compliance reporting requires sub-second aggregations over billions of rows

Rationale:
1. **Operational simplicity**: Adding ClickHouse introduces a new runtime, backup strategy, and failure domain
2. **Query flexibility**: Compliance officers need ad-hoc SQL, not just OLAP aggregations
3. **Transaction integrity**: Audit events must never be lost or duplicated; ACID matters
4. **Multi-tenant isolation**: Postgres RLS provides clean tenant boundaries without application-layer filtering

## Consequences

### Positive

- Single database technology reduces operational burden
- Workspace admins can run custom queries via existing SQL interface
- Retention policies can leverage existing pg_cron infrastructure
- PII redaction can use Postgres JSONB functional indexes

### Negative

- Aggregation queries over >6 months will be slow without materialized views
- Storage costs will be 3-4x higher than ClickHouse at equivalent retention
- Partition pruning must be carefully tuned for tenant queries

### Migration Path (if needed)

If ClickHouse is required in v3:

1. Maintain dual-write during transition
2. Use ClickHouse for read-only compliance queries
3. Retire Postgres audit storage after validation

## Open Questions

- Should audit events include full connector payload or just metadata + checksum?
- What is the target RPO for audit log writes during connector failures?