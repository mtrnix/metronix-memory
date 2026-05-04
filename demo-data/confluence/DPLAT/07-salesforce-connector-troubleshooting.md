---
space: DPLAT
slug: 07-salesforce-connector-troubleshooting
title: "Salesforce Connector — Troubleshooting Guide"
parent_slug: 02-connector-framework-overview
labels:
  - module:connector-framework
  - feature:F-A1
  - doc-type:troubleshooting
  - role:workspace-admin
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-22T13:00:00Z
version: 4
status: current
linked_jira:
  - DPLAT-DEF-02
---

# Salesforce Connector — Troubleshooting Guide

This guide helps workspace administrators diagnose and resolve common issues with the Salesforce connector. Each issue includes symptom identification, root cause analysis, resolution steps, and workarounds when applicable.

## Setup Wizard Fails

### Symptom
The connection test fails during initial connector configuration with error: `Connection timeout` or `Access denied from IP: X.X.X.X`.

### Diagnosis
The DPLAT connector requires outbound IP addresses to be whitelisted in your Salesforce organization's **Network Access** settings. This is documented in DPLAT-DEF-02. Common causes include:

- DPLAT IP ranges not added to Salesforce Trusted IP Ranges
- Corporate firewall blocking outbound connections to DPLAT endpoints
- Incorrect OAuth credentials or expired refresh tokens

### Resolution
1. Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
2. Verify OAuth credentials are valid and not expired
3. Confirm your tenant's outbound firewall allows connections to DPLAT endpoints
4. Re-run the connection test in the setup wizard

### Workaround
If IP whitelisting is not immediately possible, use the **OAuth Proxy Mode** which routes connections through your organization's outbound proxy. This requires coordination with your network team.

---

## OAuth Token Refresh Errors

### Symptom
Connector logs show intermittent `401 Unauthorized` errors with message: `OAuth token refresh failed`. Data sync stops until manually restarted.

### Diagnosis
The connector's background token refresh mechanism encountered an issue. Possible causes:

| Error Code | Meaning |
|------------|---------|
| `invalid_grant` | Refresh token expired or revoked |
| `invalid_client` | Client credentials mismatch |
| `rate_limit_exceeded` | Too many refresh attempts |

### Resolution
1. Navigate to **Connectors → Salesforce → Settings**
2. Click **Re-authenticate** to obtain new OAuth tokens
3. Verify the Salesforce Connected App still exists and is active
4. Check audit log for token revocation events

### Workaround
Enable **Token Refresh Alerting** in connector settings. This notifies workspace admins via email when refresh failures occur, allowing proactive intervention before data sync is impacted.

---

## Object Sync Delays

### Symptom
Objects configured for sync show stale data. The **Last Sync** timestamp in the connector UI is hours behind expected frequency, but no errors are logged.

### Diagnosis
Sync delays typically stem from:

- **API Rate Limits**: Salesforce has governor limits that throttle bulk operations
- **Large Object Volumes**: Objects with >100K records require incremental sync configuration
- **Query Complexity**: Custom SOQL queries with nested relationships consume more API units
- **Retention Policies**: Active retention rules may cause additional processing overhead

### Resolution
1. Review **Sync Configuration** and enable incremental sync for large objects
2. Simplify custom queries by reducing nested relationship depth
3. Adjust sync frequency to comply with your organization's API limit tier
4. Check if PII redaction rules are adding processing overhead

### Workaround
Use **Staged Sync** mode: configure critical objects (Accounts, Opportunities) on a separate schedule from archival data. This prioritizes business-critical data and reduces API consumption spikes.

---

## Health Monitor False Positives

### Symptom
The connector Health Monitor shows **Degraded** status, but manual data queries return expected results. Compliance officers report false alerts in their dashboards.

### Diagnosis
The health monitor evaluates multiple dimensions that may not reflect actual data availability:

- **Latency Thresholds**: Response time >2s triggers warning, but data is still fresh
- **Partial Object Failures**: One object failing causes overall degraded status
- **Metadata Polling**: Schema change detection may fail independently of data sync

### Resolution
1. Review **Health Monitor Details** to identify the specific failing metric
2. Adjust sensitivity thresholds in **Connector → Health Settings** (requires tenant admin)
3. Exclude non-critical objects from health monitoring via **Monitoring Configuration**
4. Verify network connectivity between DPLAT and Salesforce endpoints

### Workaround
Create a custom **Health Check Query** that validates business-critical data freshness directly. This can be scheduled independently of the built-in health monitor and provides more accurate status for compliance reporting.

---

## Escalation

If issues persist after applying resolutions, gather the following before contacting support:

- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- Salesforce org ID (first 10 characters)

Include reference to DPLAT-DEF-02 when reporting IP allowlist related issues.