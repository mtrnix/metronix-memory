---
space: DPLAT
slug: 15-connector-ops-runbook
title: "Connector Operations Runbook"
parent_slug: 02-connector-framework-overview
labels:
  - module:connector-framework
  - doc-type:runbook
  - role:workspace-admin
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-20T10:00:00Z
version: 5
status: current
linked_jira:
  - DPLAT-030
  - DPLAT-REQ-15
---

# Connector Operations Runbook

This runbook provides operational procedures for SREs and workspace administrators managing connector health, incidents, and recovery in the DPLAT environment.

## On-call rotation

The connector framework team maintains a rotating on-call schedule for production incidents.

**Rotation structure:**
- **Primary on-call**: Responds to P1/P2 incidents, performs initial triage
- **Secondary on-call**: Supports primary, handles escalated issues
- **Escalation path**: Module lead → Engineering manager → VP Engineering

**Shift handover requirements:**
- Review audit log for any anomalies in the past 24 hours
- Check connector health dashboard for degraded tenants
- Confirm no active retention policy violations
- Document any ongoing incidents in the incident tracker

## Common incident playbooks

### Connector connectivity failure

**Symptoms**: Connector status shows "Disconnected" or "Error" in workspace admin console.

**Steps:**
1. Check connector health endpoint: `GET /api/v1/connectors/{id}/health`
2. Review connector audit log for last 100 events
3. Verify data source credentials have not expired
4. Check network connectivity to data source
5. If credentials expired, initiate rotation via workspace admin console

### Sync latency degradation

**Symptoms**: Sync jobs completing slower than baseline, stale data in target.

**Steps:**
1. Query sync metrics: `GET /api/v1/connectors/{id}/metrics?window=1h`
2. Compare against baseline (typically <5min for incremental syncs)
3. Check data source for lock contention or resource exhaustion
4. If PII-heavy datasets, verify encryption/decryption overhead
5. Scale connector workers if latency >15min

### Retention policy violation

**Symptoms**: Alert triggered for data exceeding retention window.

**Steps:**
1. Identify affected tenant and connector via alert payload
2. Query retention audit log: `GET /api/v1/retention/violations?tenant={id}`
3. Determine if violation is due to misconfiguration or bug
4. Execute retention cleanup job if misconfiguration confirmed
5. Notify compliance officer if PII involved

## Recovery procedures

**Recovery target: 30 minutes**

All connector incidents must be contained and recovery initiated within 30 minutes of detection.

**Recovery steps:**
1. **Triage (0-5 min)**: Identify affected tenants, data sources, and severity
2. **Containment (5-10 min)**: Pause affected sync jobs to prevent data corruption
3. **Root cause analysis (10-20 min)**: Review audit logs, metrics, and recent deployments
4. **Recovery action (20-30 min)**: Execute appropriate remediation or failover

**Failover procedure:**
- Switch to standby connector instance if primary is compromised
- Validate data integrity post-failover
- Notify affected workspace admins via in-app notification

## Escalation matrix

| Severity | Description | Response SLA | Escalate to |
|----------|-------------|--------------|-------------|
| P1 | Complete connector outage, multiple tenants affected | 15 min | Module lead, VP Eng |
| P2 | Single connector degraded, single tenant impact | 30 min | Module lead |
| P3 | Non-critical functionality impaired | 2 hours | Primary on-call |
| P4 | Minor issue, workaround available | 8 hours | Next business day |

**Escalation contacts:**
- Module lead: connector-lead@mtrnix.example
- VP Engineering: vp-eng@mtrnix.example
- Compliance officer: compliance@mtrnix.example (for PII incidents)