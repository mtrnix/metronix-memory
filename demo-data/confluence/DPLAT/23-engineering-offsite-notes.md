---
space: DPLAT
slug: 23-engineering-offsite-notes
title: "Engineering Offsite — Berlin 2026"
parent_slug: 01-product-overview
labels:
  - doc-type:meeting-notes
  - team:platform
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-02-28T18:00:00Z
version: 1
status: current
linked_jira: []
---

# Engineering Offsite — Berlin 2026

## Overview

Two-day engineering offsite held in Berlin, January 10–11, 2026. Attendees: Platform team (12 engineers, 2 QA, 1 PM, 1 Security).

## Day 1 Sessions

### Welcome and Retrospective

Opened with team introductions and quick retros on Q4 2025. Key themes:

- Connector reliability improved but still seeing intermittent failures in the Salesforce integration
- PII handling review identified gaps in our audit log coverage for tenant data exports
- Retention policy enforcement was manually overridden three times in Q4, indicating process debt

### Connector Architecture Deep Dive

Reviewed current connector patterns with focus on:

- Error handling and retry semantics
- Idempotency guarantees
- Schema evolution handling

Team identified that our connector health monitoring lacks proper tenant-level visibility. Proposed creating per-tenant dashboards showing sync frequency, error rates, and data freshness.

### Security Workshop

Led by Security team. Covered:

- Current PII classification schema
- Encryption at rest and in transit practices
- Audit log retention requirements (currently 90 days, under review for compliance)

Action item: Document PII fields per connector in the data catalog.

## Day 2 Strategy Discussion

### 2026 Roadmap Preview

High-level themes for the year:

1. **Multi-tenant isolation** — Improve logical separation between tenants, especially for workspace admin operations
2. **Compliance tooling** — Self-serve audit log exports, retention policy configuration
3. **Connector framework** — Reduce time-to-market for new data sources

### Tenant Isolation Improvements

Current model provides database-level tenant separation, but some shared services (logging, metrics) leak context. Proposed architecture:

- Inject tenant context at the edge
- Validate tenant ID on every request
- Ensure audit log entries always include tenant identifier

### Retention Policy Automation

Compliance officer feedback indicates manual retention management is not scalable. Proposed features:

- Configurable retention periods per data category
- Automated archival and deletion jobs
- Retention audit trail (who configured what, when)

### Team Building

Afternoon dedicated to pairing exercises and trust-building. Activities included:

- System design pairing (connector failure scenarios)
- Escape room team challenge
- One-on-one check-ins with engineering manager

## Decisions Made

### Process

- **Quarterly offsites** confirmed as team ritual, alternating in-person and virtual
- **Cross-functional connector squads** formed for top 5 data sources (Salesforce, HubSpot, Snowflake, PostgreSQL, MongoDB)
- **Security review** required for any feature touching PII or audit log data

### Technical

- **PII redaction in logs** prioritized for Q1 2026
- **Tenant context middleware** to be implemented before end of Q1
- **Retention policy engine** target date: Q2 2026

### Operational

- **Workspace admin** role will get enhanced audit log visibility in next release
- **Connector reliability** target: 99.9% success rate by end of Q2
- **Sync frequency** configurability per tenant, with reasonable defaults

## Action Items

| Owner | Task | Due |
|-------|------|-----|
| Platform team | Draft connector reliability improvement plan | 2026-01-25 |
| Security | PII field catalog per connector | 2026-02-01 |
| Backend | Tenant context middleware spike | 2026-02-15 |
| PM | Retention policy feature spec | 2026-02-28 |

## Next Offsite

Tentatively scheduled for April 2026, location TBD. Focus: Q1 review and Q2 planning.