# 2.2  Monitoring and alerting

_Feature: `F-A3 Connector Health Monitor` · Audience: workspace-admin, compliance-officer_

> Real-time health tracking and alert management.

## Dashboard Overview

### How to View Connector Health Status

To view connector health status, navigate to the **Health Monitor dashboard** in the Amisol DataPlatform UI. This dashboard, implemented as a React-based frontend application ([$[health-monitor-ui]$]), provides a unified view of all connectors in your tenant.

The dashboard displays a table listing all connectors (Salesforce, SAP S/4HANA) with the following columns per [$[DPLAT-007]$]:
- **Name** – Connector identifier
- **Status** – Color-coded indicator (Green/Yellow/Red)
- **Last Sync Time** – Timestamp of most recent successful synchronization
- **Error Count** – Number of recent failures

**Status color logic** (per [$[DPLAT-007]$]):
- **Green** = Successful sync within the last 1 hour
- **Yellow** = Warning state or sync occurred 1–6 hours ago
- **Red** = Failed sync or no activity in the last 6 hours

These thresholds are configurable via workspace settings. You can filter the table by status and search by connector name, with filters persisting across page reloads. Clicking on any connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source.

The dashboard polls for updates every **5 seconds** by default (configurable via `REACT_APP_REFRESH_INTERVAL`), and supports WebSocket real-time updates when enabled.

**Note**: There is a known performance issue ([$[DPLAT-DEF-13]$]) where the dashboard may take >10 seconds to load with 50+ connectors due to individual API calls per connector. A workaround is to filter connectors by status or region to reduce the displayed count below 30.

### How to Configure Alerts for Connectivity Issues

Alerts for connector sync failures can be configured to route to **PagerDuty** and **email** ([$[DPLAT-008]$]). The alerting system works as follows:

1. **Alert triggers**: When a connector sync fails with an HTTP 5xx error (Critical severity), HTTP 4xx error (Warning severity), or timeout (Critical severity), an alert is created in the Health Monitor.
2. **PagerDuty integration**: A PagerDuty incident is triggered within **2 minutes** of alert creation, including the tenant ID and connector identifier in the payload.
3. **Email notification**: An email is sent to the workspace-admin with subject line `[Connector Alert] {connector_name} sync failure` containing a direct link to the Health Monitor dashboard.
4. **Deduplication**: Repeated failures of the same connector within a **15-minute window** do not create duplicate incidents or emails. This window is configurable per tenant.

Per the [$[Connector Operations Runbook]$], alerts can also be routed to **Slack** or **PagerDuty** (as mentioned in the module overview). The escalation matrix defines response SLAs:
- **P1** (complete outage, multiple tenants): 15-minute response SLA, escalate to Module lead and VP Engineering
- **P2** (single connector degraded): 30-minute response SLA, escalate to Module lead

### Where Are Health Metrics Stored

Health metrics are stored in the **platform observability stack** ([$[Connector Framework — Module Overview]$]), which includes:

- **Metrics**: Records synced, latency percentiles, error counts, and retry counts
- **Logs**: Structured JSON logs with correlation IDs
- **Traces**: Distributed traces for debugging cross-service issues

The Health Monitor specifically tracks:
- Connection status (healthy, degraded, disconnected)
- Sync latency per data source
- Error rates and retry counts
- Schema drift notifications

All connector configuration changes are recorded in the **audit log** with user identity, timestamp, before/after state (diff), source IP, and user agent. Compliance officers have read-only access to audit logs and PII mappings.

The status API that powers the dashboard must meet strict performance requirements ([$[DPLAT-REQ-14]$]):
- p99 read latency ≤ 1000ms under 1000 RPS
- p95 read latency ≤ 500ms
- API availability ≥ 99.9% over rolling 30-day window
- Status cache refresh interval ≤ 5 seconds for active connectors
- Graceful degradation to cached status when data source is unreachable

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)

## Metric Visualization

### How to View Connector Health Status

The primary interface for viewing connector health status is the **Health Monitor Dashboard**, implemented as a React-based frontend application in the [$[health-monitor-ui]$] repository. This dashboard provides real-time health monitoring and status visualization for the Amisol DataPlatform.

**Dashboard Features:**
- Displays a table listing all connectors (Salesforce, SAP S/4) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count** (per [$[DPLAT-007]$])
- Status colors are automatically calculated based on last sync timestamps:
  - **Green** = successful sync in the last 1 hour
  - **Yellow** = warning state or sync 1–6 hours ago
  - **Red** = failed sync or no activity in the last 6 hours
- Workspace admins can filter the table by Status and search by connector name; filtering persists across page reloads (per [$[DPLAT-007]$])
- Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source

The dashboard aggregates health signals from connected systems, displays uptime statistics, and provides drill-down capabilities for investigating connectivity issues. It polls for health data at a configurable interval (default: 5000ms) and supports WebSocket real-time updates when enabled (per [$[health-monitor-ui]$] README).

### Configuring Alerts for Connectivity Issues

Alerts for connectivity issues can be configured through the Health Monitor's alerting system. The planned v2.4 release (per [$[Release Notes — v2.4 (Planned)]$]) introduces configurable alerting channels:

**Alert Types and Severity:**
| Alert Type | Description | Severity |
|------------|-------------|----------|
| Connection Failure | Connector unable to reach data source | Critical |
| Sync Degradation | Latency exceeding threshold | Warning |
| Schema Drift | Upstream schema change detected | Warning |
| Rate Limit Exhaustion | API throttling detected | Info |

**Configuration Example (YAML):**
```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

Currently, the alerting system (per [$[DPLAT-008]$]) supports:
- **PagerDuty incidents** triggered within 2 minutes of alert creation, with the incident linked to the tenant ID and connector identifier
- **Email notifications** sent to workspace admins with subject line "[Connector Alert] {connector_name} sync failure" containing a direct link to the Health Monitor dashboard
- **Deduplication**: repeated failures of the same connector within a 15-minute window do not create duplicate alerts

**Severity mapping for sync failures** (per [$[DPLAT-008]$] comments):
- HTTP 5xx errors = Critical
- HTTP 4xx errors = Warning
- Timeout = Critical

### Where Health Metrics Are Stored

Health metrics are stored and exported through multiple mechanisms:

1. **Datadog Integration**: The Health Monitor exposes a Datadog exporter that pushes connector status, latency, and error rate metrics every 60 seconds using the StatsD protocol (per [$[DPLAT-027]$]). Exported metrics include tags for tenant, workspace, connector type, and data source name. Workspace admins can enable/disable Datadog export per workspace via the Health Monitor UI. Datadog API keys are stored as encrypted workspace secrets.

2. **Historical Metrics Storage**: The Health Monitor maintains historical health metrics and trend analysis for each connector, including uptime percentage, average latency, and error frequency (per [$[DPLAT-EPIC-03]$]).

3. **API Endpoints for Programmatic Access**: Health data is accessible via API endpoints, including:
   - `GET /api/v1/connectors/{id}/health` — check connector health status (per [$[Connector Operations Runbook]$])
   - `GET /api/v1/connectors/{id}/metrics?window=1h` — query sync metrics for a specific time window

The status read API maintains **99.9% availability** with p95 latency under 200ms and p99 under 500ms (per [$[DPLAT-REQ-05]$]), ensuring reliable access to health metrics for visualization and alerting purposes.

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)

## Real-time Status

### How to View Connector Health Status

The primary interface for viewing real-time connector health is the **Health Monitor Dashboard**, implemented as a React-based frontend application ([$[health-monitor-ui]$]). This dashboard provides a unified view of all connectors in your tenant, consolidating status indicators, last sync timestamps, and error messages into a single screen.

**Dashboard Features:**
- Displays a table listing all connectors (e.g., Salesforce, SAP S/4) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count** (per [$[DPLAT-007]$])
- Status colors are automatically calculated based on sync recency:
  - **Green** = successful sync within the last 1 hour
  - **Yellow** = warning state or sync 1–6 hours ago
  - **Red** = failed sync or no activity in the last 6 hours
- Clicking a connector row navigates to a detailed view showing the last 100 audit log entries for that data source
- Filters by Status and connector name are available, with persistence across page reloads

The dashboard polls for updates every **5 seconds** by default (configurable via `REACT_APP_REFRESH_INTERVAL`), and supports **WebSocket real-time updates** when enabled (per [$[health-monitor-ui]$]).

**API Access:** For programmatic queries, use the health endpoint: `GET /api/v1/connectors/{id}/health` (per [$[Connector Operations Runbook]$]). The status read API maintains **99.9% availability** with p95 latency under 200ms and p99 under 500ms (per [$[DPLAT-REQ-05]$]).

### How to Configure Alerts for Connectivity Issues

Alerting is configured via the **Health Monitor Alerting** feature (planned for v2.4, per [$[Release Notes — v2.4 (Planned)]$]). Workspace admins configure alerting using a YAML configuration:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

**Alert Types and Severity:**

| Alert Type | Description | Severity |
|------------|-------------|----------|
| Connection Failure | Connector unable to reach data source | Critical |
| Sync Degradation | Latency exceeding threshold | Warning |
| Schema Drift | Upstream schema change detected | Warning |
| Rate Limit Exhaustion | API throttling detected | Info |

**Current Alerting (v2.3):** The Health Monitor already supports alerting on connector sync failures via **PagerDuty** and **email** (per [$[DPLAT-008]$]):
- HTTP 5xx errors trigger **Critical** severity alerts
- HTTP 4xx errors trigger **Warning** severity
- Timeouts trigger **Critical** severity
- PagerDuty incidents are created within 2 minutes of alert creation
- Alerts are deduplicated: repeated failures of the same connector within a 15-minute window do not create duplicate incidents
- Email notifications include a direct link to the Health Monitor dashboard

### Where Health Metrics Are Stored

Health metrics are stored in two locations:

1. **Datadog** — The Health Monitor exports connector status, latency, and error rate metrics to Datadog every 60 seconds via the StatsD protocol (per [$[DPLAT-027]$]). Exported metrics include tags for tenant, workspace, connector type, and data source name. The Datadog API key and application key are stored as encrypted workspace secrets.

2. **Historical Metrics Storage** — The Health Monitor maintains historical health metrics and trend analysis for each connector, including uptime percentage, average latency, and error frequency (per [$[DPLAT-EPIC-03]$]). This enables trend analysis and compliance reporting.

**Key Performance Guarantees:**
- Status cache refresh interval ≤ 5 seconds for active connectors
- Graceful degradation: falls back to cached status when the data source is unreachable
- Auto-scaling triggered at 70% CPU utilization; recovery from node failure within 2 minutes with zero data loss (per [$[DPLAT-REQ-05]$])

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)

## Health Scoring

### How to View Connector Health Status

The primary interface for viewing connector health status is the **Health Monitor Dashboard**, implemented in the [$[health-monitor-ui]$] repository. This React-based frontend provides real-time health monitoring and status visualization for the Amisol DataPlatform.

**Dashboard Overview:**
- The dashboard displays a table listing all connectors (Salesforce, SAP S/4) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count** (per [$[DPLAT-007]$]).
- Status colors are automatically calculated based on the following thresholds (per [$[DPLAT-007]$]):
  - **Green** = successful sync in the last 1 hour
  - **Yellow** = warning state or sync 1–6 hours ago
  - **Red** = failed sync or no activity in the last 6 hours
- You can filter the table by Status and search by connector name; these filters persist across page reloads.
- Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source.

**API Access:**
- You can also query health programmatically via the endpoint: `GET /api/v1/connectors/{id}/health` (per the [$[Connector Operations Runbook]$]).
- The status read API maintains a **99.9% uptime SLA** with p95 response time under 200ms and p99 under 500ms (per [$[DPLAT-REQ-05]$]).

**Known Issue:** With 50+ active connectors, the dashboard may take >10 seconds to load due to sequential API calls. A workaround is to filter connectors by status or region to reduce the displayed count below 30 (per [$[DPLAT-DEF-13]$]).

### Configuring Alerts for Connectivity Issues

Alerts are configured through the Health Monitor's alerting system, which supports **PagerDuty** and **email** notifications (per [$[DPLAT-008]$]):

- **Alert Triggers:** When a connector sync fails with an HTTP 5xx error, an alert is created with severity "Critical" including the connector name, data source, and error details.
- **Severity Mapping:** HTTP 5xx = Critical, HTTP 4xx = Warning, timeout = Critical (per comments in [$[DPLAT-008]$]).
- **PagerDuty Integration:** A PagerDuty incident is triggered within 2 minutes of alert creation, linked to the tenant ID and connector identifier.
- **Email Notifications:** Sent to workspace-admin with subject line "[Connector Alert] {connector_name} sync failure" containing a direct link to the Health Monitor dashboard.
- **Deduplication:** Repeated failures of the same connector within a 15-minute window do not create duplicate incidents or emails.

**Alert Configuration via UI:** Workspace admins can enable/disable Datadog export per workspace via the Connector Health Monitor UI (per [$[DPLAT-027]$]).

**Known Issue:** The deduplication logic may incorrectly merge alerts from different connectors into a single incident (per [$[DPLAT-DEF-14]$]). A workaround is to manually split merged incidents or increase the deduplication window to 5 minutes.

### Where Health Metrics Are Stored

Health metrics are stored and exported through multiple channels:

1. **Datadog Integration:** The Health Monitor exposes a Datadog exporter that pushes connector status, latency, and error rate metrics every 60 seconds. Exported metrics include tags for tenant, workspace, connector type, and data source name. The Datadog API key and application key are stored as encrypted workspace secrets (per [$[DPLAT-027]$]).

2. **Historical Metrics Storage:** The system stores historical health metrics and trend analysis for each connector, including uptime percentage, average latency, and error frequency (per [$[DPLAT-EPIC-03]$]).

3. **Audit Log:** All configuration changes and health status requests are recorded in the audit log with timestamp, actor, and diff, with a retention period of 12 months (per [$[DPLAT-REQ-05]$]).

**Important Note:** Connectors in "Paused" status are incorrectly reported as "Unhealthy" with error code `CONNECTION_TIMEOUT`, causing false alerts. The workaround is to manually disable health monitoring for paused connectors by setting `health_monitor.enabled=false` (per [$[DPLAT-DEF-01]$]).

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)

## Alert Summary

### How to View Connector Health Status

The primary interface for viewing connector health status is the **Health Monitor dashboard**, a React-based UI that provides real-time status visualization for all connectors in your tenant [$[health-monitor-ui]$]. According to [$[DPLAT-007]$], the dashboard displays a table listing all connectors (Salesforce, SAP S/4HANA) with the following columns:

- **Name** of the connector
- **Status** — color-coded as Green (healthy), Yellow (degraded), or Red (failed)
- **Last Sync Time**
- **Error Count**

Status colors are automatically calculated based on sync activity:
- **Green** = successful sync within the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source. The dashboard also supports filtering by status and searching by connector name, with filters persisting across page reloads.

For programmatic access, the health status API (`GET /api/v1/connectors/{id}/health`) returns connector health data, with a p99 read latency requirement of ≤1000ms under 1000 RPS [$[DPLAT-REQ-14]$].

### How to Configure Alerts for Connectivity Issues

Alerts for connector sync failures can be routed to **PagerDuty** and **email** [$[DPLAT-008]$]. The alerting system works as follows:

- When a connector sync fails with an HTTP 5xx error, an alert is created with severity **"Critical"**, including the connector name, data source, and error details.
- A PagerDuty incident is triggered within 2 minutes of alert creation.
- An email notification is sent to the workspace admin with the subject line `[Connector Alert] {connector_name} sync failure`, containing a direct link to the Health Monitor dashboard.
- Alerts are deduplicated: repeated failures of the same connector within a **15-minute window** do not create duplicate incidents or emails.

Additionally, alerts can be routed to **Slack** or other channels, and compliance officers can access the audit log to review configuration changes [$[Connector Framework — Module Overview]$].

**Note:** There is a known bug [$[DPLAT-DEF-14]$] where the alert deduplication logic incorrectly merges alerts from different connectors into a single incident. A workaround is to manually split merged incidents in the UI or increase the deduplication window to 5 minutes.

### Where Health Metrics Are Stored

Health metrics are stored in two ways:

1. **Datadog integration**: The Health Monitor exports connector metrics (status, latency, error rates) to Datadog every 60 seconds via a StatsD protocol exporter [$[DPLAT-027]$]. Exported metrics include tags for tenant, workspace, connector type, and data source name. Workspace admins can enable/disable this export per workspace via the Health Monitor UI.

2. **Platform observability stack**: Each connector emits telemetry including metrics (records synced, latency percentiles, error counts), structured JSON logs with correlation IDs, and distributed traces for debugging cross-service issues [$[Connector Framework — Module Overview]$].

The Health Monitor dashboard itself refreshes health status every **5 seconds** by default (configurable via `REACT_APP_REFRESH_INTERVAL`), and supports WebSocket real-time updates for live status changes [$[health-monitor-ui]$].

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)

## Alert Configuration

### Viewing Connector Health Status

To view connector health status, workspace administrators use the **Health Monitor dashboard** (feature F-A3). According to [$[DPLAT-007]$], the dashboard displays a table listing all connectors (Salesforce, SAP S/4) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count**. Status colors are automatically calculated based on sync activity:
- **Green** = successful sync in the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source. The dashboard is accessible via the health-monitor-ui React application, which polls the backend API at a configurable interval (default 5000ms) per [$[health-monitor-ui]$].

### Configuring Alerts for Connectivity Issues

Alert configuration is part of the planned **v2.4 release** (per [$[Release Notes — v2.4 (Planned)]$]). Workspace administrators configure alerting via a YAML configuration block under `health_monitor.alerting`:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

The following alert types are supported:

| Alert Type | Description | Severity |
|------------|-------------|----------|
| Connection Failure | Connector unable to reach data source | Critical |
| Sync Degradation | Latency exceeding threshold | Warning |
| Schema Drift | Upstream schema change detected | Warning |
| Rate Limit Exhaustion | API throttling detected | Info |

Currently, for v2.3, the Health Monitor supports alerting on connector sync failures via **PagerDuty and email** (per [$[DPLAT-008]$]). When a connector sync fails with an HTTP 5xx error, a "Critical" alert is created. A PagerDuty incident is triggered within 2 minutes, and an email notification is sent to the workspace-admin with the subject line "[Connector Alert] {connector_name} sync failure". Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate incidents or emails.

### Where Health Metrics Are Stored

Health metrics are stored in two ways:

1. **Internal storage**: The Health Monitor maintains historical health metrics and trend analysis for each connector, including uptime percentage, average latency, and error frequency (per [$[DPLAT-EPIC-03]$]).

2. **External export**: The Health Monitor can export connector metrics to **Datadog** via a StatsD-based exporter (per [$[DPLAT-027]$]). Metrics are pushed every 60 seconds and include tags for tenant, workspace, connector type, and data source name. Workspace admins can enable/disable Datadog export per workspace via the Health Monitor UI. The Datadog API key and application key are stored as encrypted workspace secrets.

Additionally, the status read API maintains a cache with a refresh interval of ≤5 seconds for active connectors, with graceful degradation falling back to cached status when the data source is unreachable (per [$[DPLAT-REQ-14]$]).

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)

## Thresholds

### How to View Connector Health Status

The Connector Health Monitor dashboard provides a unified view of all connector statuses in your tenant. According to [$[DPLAT-007]$], the dashboard displays a table with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count**. Status colors are automatically calculated based on configurable thresholds:

- **Green** = successful sync within the last **1 hour**
- **Yellow** = warning state or sync **1–6 hours ago**
- **Red** = failed sync or no activity in the last **6 hours**

These thresholds are configurable per workspace via workspace settings (per [$[DPLAT-007]$] comment by dev2). You can also drill down into a connector's detail view to see the last 100 audit log entries.

### Configuring Alerts for Connectivity Issues

Alerts are configured through the Health Monitor's alerting system. Per [$[DPLAT-008]$], when a connector sync fails with an HTTP 5xx error, an alert is created with severity **Critical**. The system triggers a **PagerDuty incident** within 2 minutes and sends an **email notification** to the workspace-admin with subject "[Connector Alert] {connector_name} sync failure". Alerts are **deduplicated** so repeated failures of the same connector within a **15-minute window** do not create duplicate incidents.

For threshold tuning, you can adjust sensitivity in **Connector → Health Settings** (requires tenant admin) and exclude non-critical objects from monitoring via **Monitoring Configuration** (per [$[Salesforce Connector — Troubleshooting Guide]$]).

### Where Health Metrics Are Stored

Health metrics are stored in two ways:

1. **Internal storage**: The Health Monitor stores historical health metrics and trend data, including uptime percentage, average latency, and error frequency (per [$[DPLAT-EPIC-03]$]).
2. **External export**: The Health Monitor can export metrics to **Datadog** via a StatsD-based exporter that pushes connector status, latency, and error rate metrics every **60 seconds** (per [$[DPLAT-027]$]). Exported metrics include tags for tenant, workspace, connector type, and data source name. The Datadog export can be enabled/disabled per workspace via the Health Monitor UI.

### Threshold-Specific Guidance

For the **Thresholds** subsection specifically:

- **Status color thresholds** (1h/6h) are the primary mechanism for determining connector health. These are configurable per workspace.
- **Latency thresholds**: The health monitor evaluates response time; >2s triggers a warning (per [$[Salesforce Connector — Troubleshooting Guide]$]).
- **Alert deduplication window**: 15 minutes by default, configurable per tenant (per [$[DPLAT-008]$] comment by dev1).
- **Datadog export interval**: 60 seconds, fixed.
- **Dashboard refresh interval**: Configurable via `REACT_APP_REFRESH_INTERVAL` environment variable (default 5000ms) per [$[health-monitor-ui]$].

To adjust any threshold, navigate to **Connector → Health Settings** in the workspace admin console.

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)

## Notification Channels

### How to View Connector Health Status

You can view connector health status through the **Health Monitor dashboard**, a React-based UI that provides real-time status visualization for all connectors in your tenant [$[health-monitor-ui]$]. The dashboard displays a table listing all connectors (Salesforce, SAP S/4) with columns for Name, Status (Green/Yellow/Red), Last Sync Time, and Error Count [$[DPLAT-007]$]. Status colors are automatically calculated: **Green** = successful sync in last 1 hour, **Yellow** = warning state or sync 1-6 hours ago, **Red** = failed sync or no activity in last 6 hours [$[DPLAT-007]$]. Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source [$[DPLAT-007]$].

### Configuring Alerts for Connectivity Issues

The Health Monitor supports multiple notification channels for alerting on connector issues:

**1. PagerDuty Incidents** — When a connector sync fails with an HTTP 5xx error, a PagerDuty incident is triggered within 2 minutes of alert creation, with severity "Critical" [$[DPLAT-008]$]. The incident payload includes the tenant ID and connector identifier. Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate incidents [$[DPLAT-008]$].

**2. Email Notifications** — An email is sent to the workspace-admin with the subject line `[Connector Alert] {connector_name} sync failure`, containing a direct link to the Health Monitor dashboard [$[DPLAT-008]$]. Additionally, a **weekly digest email** is sent every Monday at 08:00 UTC summarizing connector health status across all data sources, including status indicators and last successful sync timestamps [$[DPLAT-028]$]. The digest is suppressed if all connectors are healthy and no warnings occurred during the reporting period [$[DPLAT-028]$].

**3. Datadog Integration** — The Health Monitor exports connector status, latency, and error rate metrics to Datadog every 60 seconds using the StatsD protocol [$[DPLAT-027]$]. Exported metrics include tags for tenant, workspace, connector type, and data source name. Workspace admins can enable/disable Datadog export per workspace via the Health Monitor UI [$[DPLAT-027]$].

**4. Token Refresh Alerting** — For Salesforce connectors specifically, you can enable **Token Refresh Alerting** in connector settings, which notifies workspace admins via email when OAuth token refresh failures occur [$[Salesforce Connector — Troubleshooting Guide]$].

### Where Health Metrics Are Stored

Health metrics are stored in the Health Monitor's internal storage system, which supports historical metrics retrieval and trend analysis, including uptime percentage, average latency, and error frequency [$[DPLAT-EPIC-03]$]. The status read API maintains a cache with a refresh interval of ≤5 seconds for active connectors, with graceful degradation falling back to cached status when a data source is unreachable [$[DPLAT-REQ-14]$]. For external storage, metrics can be exported to Datadog as described above.

### Important Notes on Alerting Behavior

- **Known issue**: When a connector is in "Paused" status, the Health Monitor incorrectly reports it as "Unhealthy" with error code `CONNECTION_TIMEOUT`, causing false alerts [$[DPLAT-DEF-01]$]. A workaround is to manually disable health monitoring for paused connectors by setting `health_monitor.enabled=false`.
- **Known issue**: Alert deduplication may incorrectly merge alerts from different connectors into a single incident, causing confusion during incident review [$[DPLAT-DEF-14]$]. A workaround is to manually split merged incidents in the UI or increase the deduplication window.

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)

## Escalation

### How to View Connector Health Status

To view connector health status, workspace administrators use the **Health Monitor dashboard** ([$[DPLAT-007]$]), a React-based UI that displays a unified table of all connectors (Salesforce, SAP S/4) with columns for Name, Status (Green/Yellow/Red), Last Sync Time, and Error Count. Status colors are automatically calculated: **Green** = successful sync in the last hour, **Yellow** = warning state or sync 1–6 hours ago, **Red** = failed sync or no activity in the last 6 hours. Clicking a connector row navigates to a detailed view showing the last 100 audit log entries for that data source.

### How to Configure Alerts for Connectivity Issues

Alerts are configured via the Health Monitor's alerting system ([$[DPLAT-008]$], [$[DPLAT-EPIC-03]$]). Workspace admins can set up automated notifications through:

- **PagerDuty**: Incidents are triggered within 2 minutes of a critical sync failure (HTTP 5xx errors, timeouts), with the incident payload containing tenant ID and connector identifier.
- **Email**: Notifications are sent with subject line "[Connector Alert] {connector_name} sync failure" and a direct link to the dashboard.
- **Webhook** (planned for v2.4): Configurable via YAML with severity filters (critical, warning, info) and custom URLs.

Alerts are deduplicated: repeated failures of the same connector within a 15-minute window do not create duplicate incidents or emails. The deduplication window is configurable per tenant.

### Where Health Metrics Are Stored

Health metrics are stored in two locations:

1. **Internal storage**: Historical health metrics (uptime percentage, average latency, error frequency) are stored for trend analysis and retrieval via API endpoints ([$[DPLAT-EPIC-03]$]).
2. **Datadog** (optional): The Health Monitor exports connector status, latency, and error rate metrics every 60 seconds to Datadog via StatsD protocol ([$[DPLAT-027]$]). Exported metrics include tags for tenant, workspace, connector type, and data source name. Workspace admins can enable/disable this export per workspace.

### Escalation Path

The escalation matrix for connector health incidents is defined in the [$[Connector Operations Runbook]$]:

| Severity | Description | Response SLA | Escalate to |
|----------|-------------|--------------|-------------|
| **P1** | Complete connector outage, multiple tenants affected | 15 min | Module lead, VP Engineering |
| **P2** | Single connector degraded, single tenant impact | 30 min | Module lead |
| **P3** | Non-critical functionality impaired | 2 hours | Primary on-call |
| **P4** | Minor issue, workaround available | 8 hours | Next business day |

**Escalation contacts:**
- Module lead: connector-lead@mtrnix.example
- VP Engineering: vp-eng@mtrnix.example
- Compliance officer: compliance@mtrnix.example (for PII incidents)

The on-call rotation includes a **Primary on-call** (responds to P1/P2 incidents, performs initial triage) and a **Secondary on-call** (supports primary, handles escalated issues). The full escalation path is: Primary on-call → Secondary on-call → Module lead → Engineering manager → VP Engineering.

If issues persist after applying resolutions, gather the following before contacting support ([$[Salesforce Connector — Troubleshooting Guide]$]):
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- Salesforce org ID (first 10 characters)

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)

## Severity Levels

The Connector Health Monitor (feature F-A3) implements a multi-tier severity system that determines how connector health status is displayed and how alerts are triggered. Here is how severity levels work across the monitoring and alerting system:

### Viewing Connector Health Status by Severity

The Health Monitor dashboard (implemented in the [$[health-monitor-ui]$] React application) displays connector status using a color-coded severity system:

- **Green (Healthy)**: Connector successfully synced within the last 1 hour. No action required.
- **Yellow (Warning/Degraded)**: Connector synced 1-6 hours ago, or is in a warning state (e.g., sync latency degradation, schema drift detected). Per the [$[Release Notes — v2.4 (Planned)]$], sync degradation and schema drift are classified as "Warning" severity.
- **Red (Critical/Failed)**: Connector sync failed, or no activity in the last 6 hours. This includes connection failures (classified as "Critical" per the release notes) and HTTP 5xx errors (classified as "Critical" per [$[DPLAT-008]$]).

The dashboard shows a table with columns for Name, Status (Green/Yellow/Red), Last Sync Time, and Error Count. Clicking a connector row navigates to a detailed view with the last 100 audit log entries.

### Configuring Alerts by Severity

Alerts are configured based on severity levels, as documented in the v2.4 release notes. The alert configuration uses a YAML structure where you define channels (webhook, email) and apply a `severity_filter` to control which severity levels trigger notifications:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

The four alert types and their severity mappings are:

| Alert Type | Severity |
|------------|----------|
| Connection Failure | Critical |
| Sync Degradation | Warning |
| Schema Drift | Warning |
| Rate Limit Exhaustion | Info |

Per [$[DPLAT-008]$], HTTP 5xx errors trigger "Critical" alerts, HTTP 4xx errors trigger "Warning" alerts, and timeouts trigger "Critical" alerts. Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate incidents.

### Where Health Metrics Are Stored

Health metrics are stored in the backend system accessible via the API endpoint configured through the `REACT_APP_API_URL` environment variable (default: `http://localhost:8080`). The health monitor polls this endpoint at an interval configured by `REACT_APP_REFRESH_INTERVAL` (default: 5000ms). Historical health metrics and trend analysis (uptime percentage, average latency, error frequency) are stored for retrieval, as specified in [$[DPLAT-EPIC-03]$]. The status API must maintain p99 read latency under 1000ms and p95 under 500ms per [$[DPLAT-REQ-14]$], with a status cache refresh interval of ≤5 seconds for active connectors.

### Important Note on Paused Connectors

There is a known defect ([$[DPLAT-DEF-01]$]) where connectors in "Paused" status are incorrectly reported as "Unhealthy" with error code `CONNECTION_TIMEOUT`, causing false alerts. The expected behavior is that paused connectors should be excluded from health monitoring or reported as "Degraded" with a clear indication of the pause state. A workaround exists by setting `health_monitor.enabled=false` for paused connectors, though this requires a connector restart.

**Sources:**
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)

## Log Analysis

### How to View Connector Health Status

To view connector health status through log analysis, you can access the **Health Monitor dashboard** — a React-based UI that provides real-time status visualization for all connectors in your tenant [$[health-monitor-ui]$]. The dashboard displays a table with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count** [$[DPLAT-007]$]. 

For log-specific analysis, clicking on a connector row navigates to a detailed view showing the **last 100 audit log entries** for that data source [$[DPLAT-007]$]. You can also query the connector health endpoint directly: `GET /api/v1/connectors/{id}/health` and review the connector audit log for the last 100 events [$[Connector Operations Runbook]$].

Status colors are automatically calculated based on sync activity:
- **Green** = successful sync in the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours [$[DPLAT-007]$]

### How to Configure Alerts for Connectivity Issues

Alerts for connectivity issues can be configured through the **Health Monitor alerting system**, which supports multiple channels. The planned v2.4 release introduces configurable alerting via YAML configuration [$[Release Notes — v2.4 (Planned)]$]:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

Alert types include:
- **Connection Failure** (Critical) — connector unable to reach data source
- **Sync Degradation** (Warning) — latency exceeding threshold
- **Schema Drift** (Warning) — upstream schema change detected
- **Rate Limit Exhaustion** (Info) — API throttling detected [$[Release Notes — v2.4 (Planned)]$]

Currently, alerts are being implemented for **PagerDuty and email** notifications when connector sync failures occur (e.g., HTTP 5xx errors trigger Critical alerts, HTTP 4xx trigger Warning) [$[DPLAT-008]$]. Alerts are deduplicated so repeated failures within a 15-minute window do not create duplicate incidents [$[DPLAT-008]$].

### Where Health Metrics Are Stored

Health metrics are stored in multiple locations for different purposes:

1. **Datadog** — The Health Monitor exports connector status, latency, and error rate metrics to Datadog every 60 seconds via a StatsD-based exporter. Metrics include tags for tenant, workspace, connector type, and data source name [$[DPLAT-027]$].

2. **Audit Log** — All health check API calls create audit log entries with 12-month retention [$[DPLAT-REQ-05]$]. The audit log export job status is also displayed in the Health Monitor dashboard [$[DPLAT-043]$].

3. **Historical Metrics Storage** — The Connector Health Monitor epic (DPLAT-EPIC-03) specifies storage for historical health metrics and trend analysis, including uptime percentage, average latency, and error frequency [$[DPLAT-EPIC-03]$].

For log analysis specifically, the **audit log** is the primary source — you can review the last 100 events per connector via the dashboard detail view or query the retention audit log endpoint: `GET /api/v1/retention/violations?tenant={id}` [$[Connector Operations Runbook]$].

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)

## Metric Logs

### How to View Connector Health Status

You can view connector health status through the **Health Monitor Dashboard** (feature F-A3), which is implemented in the [$[health-monitor-ui]$] React-based frontend application. The dashboard provides a unified view of all connectors in your tenant, displaying:

- **Connector Name** and **Data Source** type
- **Status indicator** (Green/Yellow/Red) — automatically calculated based on last sync time:
  - **Green** = successful sync within the last 1 hour
  - **Yellow** = warning state or sync 1–6 hours ago
  - **Red** = failed sync or no activity in the last 6 hours
- **Last Sync Time** timestamp
- **Error Count** for each connector

To access the dashboard, navigate to the Health Monitor UI (default at `http://localhost:3000` during development). The dashboard polls for updates every 5 seconds by default (configurable via `REACT_APP_REFRESH_INTERVAL`). Clicking on any connector row opens a detailed view showing the last 100 audit log entries for that specific data source (per [$[DPLAT-007]$]).

For programmatic access, use the health endpoint: `GET /api/v1/connectors/{id}/health` (per the [$[Connector Operations Runbook]$]).

### How to Configure Alerts for Connectivity Issues

Alerts for connectivity issues are configured through the **Health Monitor Alerting** system. The planned v2.4 release (per [$[Release Notes — v2.4 (Planned)]$]) introduces configurable alerting channels with the following alert types:

| Alert Type | Description | Severity |
|------------|-------------|----------|
| Connection Failure | Connector unable to reach data source | Critical |
| Sync Degradation | Latency exceeding threshold | Warning |
| Schema Drift | Upstream schema change detected | Warning |
| Rate Limit Exhaustion | API throttling detected | Info |

**Configuration example** (YAML format):
```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

Currently, the system supports alerting via **PagerDuty** and **email** (per [$[DPLAT-008]$]). When a connector sync fails with an HTTP 5xx error, a "Critical" alert is created, a PagerDuty incident is triggered within 2 minutes, and an email notification is sent to the workspace admin. Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate incidents.

**Note:** There is a known bug ([$[DPLAT-DEF-01]$]) where paused connectors are incorrectly reported as "Unhealthy" with `CONNECTION_TIMEOUT`, triggering false alerts. A workaround is to manually set `health_monitor.enabled=false` for paused connectors.

### Where Are Health Metrics Stored?

Health metrics are stored and exported through multiple channels:

1. **Datadog Integration** — The Health Monitor exports connector status, latency, and error rate metrics to Datadog every 60 seconds using the StatsD protocol (per [$[DPLAT-027]$]). Exported metrics include tags for tenant, workspace, connector type, and data source name. The Datadog API key and application key are stored as encrypted workspace secrets.

2. **Health Monitor Dashboard** — The UI itself stores and displays historical health metrics, including uptime percentage, average latency, and error frequency for trend analysis (per [$[DPLAT-EPIC-03]$]).

3. **Audit Logs** — Each health status API call creates an audit log entry with 12-month retention (per [$[DPLAT-REQ-05]$]).

4. **PII Classifier Latency Metrics** — The Health Monitor also surfaces PII classifier latency metrics (p50, p95, p99) per connector, updated with a maximum 5-minute delay (per [$[DPLAT-041]$]).

**Key metric endpoints:**
- Connector health: `GET /api/v1/connectors/{id}/health`
- Sync metrics: `GET /api/v1/connectors/{id}/metrics?window=1h`
- Retention audit log: `GET /api/v1/retention/violations?tenant={id}`

The status read API maintains a p99 latency under 1000ms and 99.9% availability (per [$[DPLAT-REQ-14]$] and [$[DPLAT-REQ-05]$]).

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)

## Event History

### How to View Connector Health Status

To view connector health status, workspace administrators use the **Health Monitor Dashboard** (feature F-A3), which provides a unified real-time view of all connectors in the tenant. According to [$[DPLAT-007]$], the dashboard displays a table listing all connectors (Salesforce, SAP S/4) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count**. Clicking on a connector row navigates to a detailed view showing the **last 100 audit log entries** for that specific data source — this is the primary "Event History" interface.

The status colors are automatically calculated based on sync timestamps (per [$[DPLAT-007]$]):
- **Green** = successful sync in the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

These thresholds are configurable via workspace settings. The dashboard can be filtered by status and searched by connector name, with filters persisting across page reloads.

### How to Configure Alerts for Connectivity Issues

Alerts for connectivity issues are configured through the Health Monitor's alerting system. Per [$[DPLAT-008]$], when a connector sync fails with an HTTP 5xx error, an alert is created with severity **"Critical"** containing the connector name, data source, and error details. The system then:
- Triggers a **PagerDuty incident** within 2 minutes
- Sends an **email notification** to the workspace-admin with subject "[Connector Alert] {connector_name} sync failure" and a direct link to the Health Monitor dashboard

Alerts are **deduplicated** — repeated failures of the same connector within a 15-minute window do not create duplicate incidents or emails. The deduplication window is configurable per tenant. Alerts can also be routed to **Slack** or other channels (per the [$[Connector Framework — Module Overview]$]).

For HTTP 4xx errors, alerts are set to **"Warning"** severity, and timeouts are treated as **"Critical"** (per [$[DPLAT-008]$] comments).

### Where Health Metrics Are Stored

Health metrics are stored in multiple locations:

1. **Audit Log**: All connector configuration changes and health events are recorded in the audit log with user identity, timestamp, before/after state (diff), source IP, and user agent (per [$[Connector Framework — Module Overview]$]). The audit log retains entries for **12 months** (per [$[DPLAT-REQ-05]$]).

2. **Datadog**: The Health Monitor exports connector status, latency, and error rate metrics to **Datadog** every 60 seconds via a StatsD exporter (per [$[DPLAT-027]$]). Exported metrics include tags for tenant, workspace, connector type, and data source name. Workspace admins can enable/disable this export per workspace via the Health Monitor UI.

3. **Health Monitor API**: Historical health metrics and trend analysis are stored for retrieval, including uptime percentage, average latency, and error frequency (per [$[DPLAT-EPIC-03]$]). The status API maintains a cache with a refresh interval of ≤5 seconds for active connectors, with graceful degradation to cached status when the data source is unreachable (per [$[DPLAT-REQ-14]$]).

4. **Connector Audit Log**: For specific connectors, you can query the audit log via `GET /api/v1/connectors/{id}/health` and review the last 100 events (per the [$[Connector Operations Runbook]$]).

### Event History Summary

The **Event History** aspect is primarily accessed through the **audit log** in the connector detail view (last 100 entries per connector) and the **Datadog metrics** for longer-term trend analysis. For compliance officers, the audit log provides read-only access with PII-tagged fields masked for non-compliance-officer users (per [$[DPLAT-007]$] QA comment).

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)

## Error Logs

### How to View Connector Health Status

To view connector health status, workspace administrators use the **Health Monitor dashboard** ([$[DPLAT-007]$]), which is implemented in the [$[health-monitor-ui]$] React-based frontend application. The dashboard provides a unified view of all connectors in your tenant with the following key features:

1. **Main Dashboard View**: Displays a table listing all connectors (Salesforce, SAP S/4) with columns for Name, Status (Green/Yellow/Red), Last Sync Time, and Error Count ([$[DPLAT-007]$]).

2. **Detailed Connector View**: Clicking on a connector row navigates to a detailed view showing the last **100 audit log entries** for that specific data source ([$[DPLAT-007]$]). This is where you can examine error logs in depth.

3. **Status Calculation**: Status colors are automatically calculated based on sync timestamps:
   - **Green** = successful sync in the last 1 hour
   - **Yellow** = warning state or sync 1-6 hours ago
   - **Red** = failed sync or no activity in the last 6 hours ([$[DPLAT-007]$])

4. **Filtering**: You can filter the table by Status and search by connector name; filtering persists across page reloads ([$[DPLAT-007]$]).

### How to Configure Alerts for Connectivity Issues

Alerts for connectivity issues are configured through the Health Monitor's alerting system ([$[DPLAT-008]$]):

- **Automatic Alerting**: When a connector sync fails with an HTTP 5xx error, an alert is created with severity "Critical" and includes the connector name, data source, and error details ([$[DPLAT-008]$]).
- **Notification Channels**: Alerts are sent via **PagerDuty** (incident triggered within 2 minutes) and **email** (subject line: "[Connector Alert] {connector_name} sync failure" with a direct link to the dashboard) ([$[DPLAT-008]$]).
- **Deduplication**: Repeated failures of the same connector within a 15-minute window do not create duplicate incidents or emails ([$[DPLAT-008]$]).
- **Severity Mapping**: HTTP 5xx = Critical, HTTP 4xx = Warning, timeout = Critical ([$[DPLAT-008]$] comments).

### Where Health Metrics Are Stored

Health metrics are stored and exported through multiple channels:

1. **Datadog Integration**: The Health Monitor exports connector status, latency, and error rate metrics to Datadog every 60 seconds via the StatsD protocol ([$[DPLAT-027]$]). Metrics include tags for tenant, workspace, connector type, and data source name.

2. **Health Monitor API**: The status read API must maintain 99.9% availability with p95 response time under 200ms and support 1000 requests per second per tenant ([$[DPLAT-REQ-05]$]).

3. **Audit Logs**: The dashboard includes an "Audit Log Export" panel showing the most recent export job status (Success, In Progress, Failed, or Not Run) with timestamps and links to full export history ([$[DPLAT-043]$]).

### Error Logs-Specific Guidance

For investigating error logs specifically:

- **Audit Log Detail View**: Navigate to a specific connector's detail view to see the last 100 audit log entries ([$[DPLAT-007]$]).
- **Connector Health Endpoint**: Use `GET /api/v1/connectors/{id}/health` to check connector status programmatically ([$[Connector Operations Runbook]$]).
- **Audit Log Review**: Review the connector audit log for the last 100 events when diagnosing connectivity failures ([$[Connector Operations Runbook]$]).
- **Known Issue**: Be aware that connectors in "Paused" status may incorrectly show as "Unhealthy" with error code `CONNECTION_TIMEOUT` — this is a known bug ([$[DPLAT-DEF-01]$]). The workaround is to manually set `health_monitor.enabled=false` for paused connectors.

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)

## Diagnostic Data

### How to View Connector Health Status

You can view connector health status through the **Health Monitor dashboard**, which provides a unified real-time view of all connectors in your tenant. According to [$[DPLAT-007]$], the dashboard displays a table with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count**. Status colors are automatically calculated based on the following thresholds:

- **Green**: Successful sync within the last 1 hour
- **Yellow**: Warning state or sync 1–6 hours ago
- **Red**: Failed sync or no activity in the last 6 hours

These thresholds are configurable via workspace settings. Clicking on any connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source. The dashboard also supports filtering by status and searching by connector name, with filters persisting across page reloads.

For programmatic access, you can query the health endpoint directly: `GET /api/v1/connectors/{id}/health` (per the [$[Connector Operations Runbook]$]).

### How to Configure Alerts for Connectivity Issues

Alerting is configured via the **Health Monitor** settings. Per the planned [$[Release Notes — v2.4 (Planned)]$], workspace admins can configure alerting channels using a YAML configuration:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

The following alert types are supported:

| Alert Type | Description | Severity |
|------------|-------------|----------|
| Connection Failure | Connector unable to reach data source | Critical |
| Sync Degradation | Latency exceeding threshold | Warning |
| Schema Drift | Upstream schema change detected | Warning |
| Rate Limit Exhaustion | API throttling detected | Info |

According to [$[DPLAT-008]$], when a connector sync fails with an HTTP 5xx error, a **PagerDuty incident** is triggered within 2 minutes, and an **email notification** is sent to the workspace admin with the subject line `[Connector Alert] {connector_name} sync failure`. Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate incidents or emails.

### Where Are Health Metrics Stored?

Health metrics are stored in two ways:

1. **Datadog**: Per [$[DPLAT-027]$], the Health Monitor exports connector status, latency, and error rate metrics to **Datadog** every 60 seconds using the StatsD protocol. Exported metrics include tags for tenant, workspace, connector type, and data source name. The Datadog API key and application key are stored as encrypted workspace secrets.

2. **Historical Metrics Storage**: The [$[DPLAT-EPIC-03]$] epic specifies that the Health Monitor includes **historical metrics storage and retrieval** for trend analysis, including uptime percentage, average latency, and error frequency. The specific storage backend (database) is not detailed in the provided sources, but the metrics are accessible via the dashboard and API endpoints.

For diagnostic purposes, you can also query sync metrics directly: `GET /api/v1/connectors/{id}/metrics?window=1h` (per the [$[Connector Operations Runbook]$]).

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)

## System Health Audit

### How to View Connector Health Status

To view connector health status, use the **Health Monitor Dashboard** — a React-based UI that serves as the primary interface for operations teams. According to [$[health-monitor-ui]$], this dashboard aggregates health signals from connected systems and displays uptime statistics with drill-down capabilities.

The dashboard provides a unified table listing all connectors (e.g., Salesforce, SAP S/4) with the following columns per [$[DPLAT-007]$]:
- **Name** of the connector
- **Status** indicator (Green/Yellow/Red)
- **Last Sync Time**
- **Error Count**

Status colors are automatically calculated based on sync activity:
- **Green** = successful sync within the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

Clicking on any connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source. You can filter the table by status and search by connector name, with filters persisting across page reloads.

For programmatic access, the health status API is available at `GET /api/v1/connectors/{id}/health` per the [$[Connector Operations Runbook]$]. The API maintains a p99 read latency of ≤1000ms under 1000 RPS and 99.9% availability per [$[DPLAT-REQ-05]$] and [$[DPLAT-REQ-14]$].

### How to Configure Alerts for Connectivity Issues

Alerts can be configured through the Health Monitor's automated alerting mechanisms. Per [$[DPLAT-008]$], when a connector sync fails:

1. **Alert Creation**: A "Critical" severity alert is created containing the connector name, data source, and error details
2. **PagerDuty Integration**: A PagerDuty incident is triggered within 2 minutes of alert creation, linked to the tenant ID and connector identifier
3. **Email Notification**: An email is sent to the workspace-admin with subject "[Connector Alert] {connector_name} sync failure" containing a direct link to the Health Monitor dashboard
4. **Deduplication**: Repeated failures of the same connector within a 15-minute window do not create duplicate incidents or emails

Severity mapping for alerts:
- HTTP 5xx errors → Critical
- HTTP 4xx errors → Warning
- Timeout errors → Critical

Additionally, per [$[DPLAT-027]$], the Health Monitor exports connector status, latency, and error rate metrics to **Datadog** every 60 seconds, enabling unified alerting through your existing APM platform. You can enable or disable Datadog export per workspace via the Health Monitor UI.

For on-call teams, the [$[Connector Operations Runbook]$] defines an escalation matrix:
- **P1** (complete outage, multiple tenants): 15-minute response SLA, escalate to Module lead and VP Engineering
- **P2** (single connector degraded): 30-minute response SLA, escalate to Module lead
- **P3** (non-critical impairment): 2-hour response SLA
- **P4** (minor issue): 8-hour response SLA

### Where Health Metrics Are Stored

Health metrics are stored in multiple locations depending on the use case:

1. **Health Monitor Dashboard Cache**: Status data is cached with a refresh interval of ≤5 seconds for active connectors per [$[DPLAT-REQ-14]$]. The dashboard polls the backend API at a configurable interval (default 5000ms) per [$[health-monitor-ui]$].

2. **Audit Log**: All configuration changes and health events are recorded in the audit log with timestamp, actor, and diff per the [$[Connector Configuration API]$]. The audit log retains entries for 12 months per [$[DPLAT-REQ-05]$].

3. **Datadog**: Metrics (connector status, latency, error rate) are pushed to Datadog every 60 seconds with tags for tenant, workspace, connector type, and data source name per [$[DPLAT-027]$].

4. **Historical Metrics Storage**: The [$[DPLAT-EPIC-03]$] epic specifies that historical health metrics and trend analysis are stored for each connector, including uptime percentage, average latency, and error frequency — enabling trend analysis over time.

**Note**: There is a known performance issue — the dashboard takes >10 seconds to load with 50+ connectors due to sequential API calls per [$[DPLAT-DEF-13]$]. A workaround is to filter connectors by status or region to reduce the displayed count below 30, or use the bulk export feature.

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)

## Uptime Tracking

### How to View Connector Health Status

To view connector health status for uptime tracking, workspace administrators use the **Health Monitor dashboard** — a React-based UI that provides real-time health monitoring and status visualization for all connectors in the tenant [$[health-monitor-ui]$]. The dashboard displays a table listing all connectors (Salesforce, SAP S/4, etc.) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count** [$[DPLAT-007]$].

Status colors are automatically calculated based on uptime criteria:
- **Green** = successful sync within the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

These thresholds are configurable via workspace settings [$[DPLAT-007]$]. Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source [$[DPLAT-007]$]. The dashboard also includes an **"Audit Log Export" panel** showing the most recent export job status (Success, In Progress, Failed, or Not Run) with consistent color coding [$[DPLAT-043]$].

For programmatic access, the health status API endpoint is available at `GET /api/v1/connectors/{id}/health` [$[Connector Operations Runbook]$]. The status read API must maintain **99.9% availability** with p95 latency under 500ms and p99 under 1000ms [$[DPLAT-REQ-05]$][$[DPLAT-REQ-14]$].

### How to Configure Alerts for Connectivity Issues

Alerts for connectivity issues are configured via the Health Monitor's alerting system. Workspace admins can configure alerting channels using YAML configuration [$[Release Notes — v2.4 (Planned)]$]:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

Alert types include:
- **Connection Failure** (Critical) — connector unable to reach data source
- **Sync Degradation** (Warning) — latency exceeding threshold
- **Schema Drift** (Warning) — upstream schema change detected
- **Rate Limit Exhaustion** (Info) — API throttling detected

When a connector sync fails with an HTTP 5xx error, a **Critical** alert is created, triggering a **PagerDuty incident** within 2 minutes and an **email notification** to the workspace admin with subject line "[Connector Alert] {connector_name} sync failure" [$[DPLAT-008]$]. Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate incidents [$[DPLAT-008]$].

Additionally, a **weekly digest email** is sent every Monday at 08:00 UTC summarizing connector health status, including status indicators and last successful sync timestamps [$[DPLAT-028]$].

### Where Health Metrics Are Stored

Health metrics are stored in two primary locations:

1. **Historical metrics storage** — The Health Monitor stores historical health metrics and trend analysis for each connector, including uptime percentage, average latency, and error frequency. This data is used for trend analysis and is accessible via the dashboard [$[DPLAT-EPIC-03]$].

2. **Datadog integration** — The Health Monitor exports connector metrics (status, latency, error rate) to **Datadog** every 60 seconds via a StatsD exporter. Exported metrics include tags for tenant, workspace, connector type, and data source name. Workspace admins can enable/disable this export per workspace via the UI, and the Datadog API key is stored as an encrypted workspace secret [$[DPLAT-027]$].

The health monitoring service itself must maintain **99.5% uptime** [$[DPLAT-EPIC-03]$], and the status cache refreshes every **5 seconds** for active connectors, with graceful degradation falling back to cached status when the data source is unreachable [$[DPLAT-REQ-14]$].

**Sources:**
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)

## Performance History

To view connector health status with a focus on **Performance History**, workspace administrators use the **Health Monitor dashboard** ([$[DPLAT-007]$]). This dashboard provides a unified view of all connectors (Salesforce, SAP S/4HANA) with real-time status indicators and historical performance data.

### Primary: How to View Connector Health Status

The Health Monitor dashboard displays a table with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count** ([$[DPLAT-007]$]). Status colors are automatically calculated based on sync recency:

- **Green** = successful sync in the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

These thresholds are configurable via workspace settings ([$[DPLAT-007]$]). Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that data source, allowing you to investigate performance history and past incidents.

For programmatic access, the health status API is available at `GET /api/v1/connectors/{id}/health` ([$[Connector Operations Runbook]$]). The API maintains a p99 read latency under 1000ms and p95 under 500ms, with a status cache refresh interval of ≤5 seconds for active connectors ([$[DPLAT-REQ-14]$], [$[DPLAT-REQ-05]$]).

### Related: Configuring Alerts for Connectivity Issues

Alerts can be configured to notify you of connectivity failures. The Health Monitor supports alerting via **PagerDuty** and **email** ([$[DPLAT-008]$]). When a connector sync fails with an HTTP 5xx error, a "Critical" alert is created, a PagerDuty incident is triggered within 2 minutes, and an email is sent with a direct link to the dashboard. Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate notifications ([$[DPLAT-008]$]).

In the planned v2.4 release, alerting will become configurable via YAML, supporting webhook and email channels with severity filters for critical, warning, and info levels ([$[Release Notes — v2.4 (Planned)]$]).

### Where Health Metrics Are Stored

Health metrics are stored in the **platform observability stack**, which includes:

- **Metrics**: records synced, latency percentiles, error counts, and retry counts ([$[Connector Framework — Module Overview]$])
- **Logs**: structured JSON logs with correlation IDs
- **Traces**: distributed traces for debugging cross-service issues

Additionally, the Health Monitor exports connector metrics to **Datadog** every 60 seconds via a StatsD exporter, with tags for tenant, workspace, connector type, and data source name ([$[DPLAT-027]$]). This enables correlation of data pipeline health with application performance and unified alerting. The Datadog exporter can be enabled/disabled per workspace through the Health Monitor UI ([$[DPLAT-027]$]).

For **Performance History** specifically, the Health Monitor tracks historical metrics including uptime percentage, average latency, and error frequency per connector, enabling trend analysis ([$[DPLAT-EPIC-03]$]).

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)

## Alert Logs

### How to View Connector Health Status

To view connector health status, access the **Health Monitor dashboard** — a React-based frontend application ([$[health-monitor-ui]$]) that provides real-time status visualization for all connectors in your tenant. The dashboard displays a table listing all connectors (Salesforce, SAP S/4HANA) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count** (per [$[DPLAT-007]$]).

Status colors are automatically calculated:
- **Green** = successful sync in the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

Clicking on a connector row navigates to a detailed view showing the **last 100 audit log entries** for that specific data source. You can filter the table by Status and search by connector name, with filters persisting across page reloads (per [$[DPLAT-007]$]).

The dashboard polls for updates every 5 seconds by default (configurable via `REACT_APP_REFRESH_INTERVAL`), and supports WebSocket real-time updates when enabled (per [$[health-monitor-ui]$]).

### How to Configure Alerts for Connectivity Issues

Alerts can be configured to notify you automatically when connector sync failures occur. The system supports routing alerts to **PagerDuty**, **email**, **Slack**, or **PagerDuty** (per [$[DPLAT-008]$] and [$[Connector Framework — Module Overview]$]).

**Alert triggers and severity mapping** (per [$[DPLAT-008]$]):
- **HTTP 5xx errors** → Critical severity → PagerDuty incident triggered within 2 minutes
- **HTTP 4xx errors** → Warning severity
- **Timeouts** → Critical severity

**Email notifications** are sent to workspace admins with subject line: `[Connector Alert] {connector_name} sync failure`, containing a direct link to the Health Monitor dashboard.

**Deduplication**: Alerts from the same connector within a 15-minute window are deduplicated to prevent duplicate incidents. However, note a known bug ([$[DPLAT-DEF-14]$]) where alerts from **different connectors** may be incorrectly merged into a single incident — this is currently under investigation.

**Known issue**: Connectors in "Paused" status are incorrectly reported as "Unhealthy" with `CONNECTION_TIMEOUT`, triggering false alerts ([$[DPLAT-DEF-01]$]). The workaround is to manually disable health monitoring for paused connectors via the `health_monitor.enabled=false` configuration flag.

### Where Are Health Metrics Stored?

Health metrics are stored and exported through multiple channels:

1. **Datadog integration**: The Health Monitor exports connector status, latency, and error rate metrics every 60 seconds to Datadog via StatsD protocol, with tags for tenant, workspace, connector type, and data source name ([$[DPLAT-027]$]). Workspace admins can enable/disable this export per workspace via the UI.

2. **Platform observability stack**: Each connector emits telemetry including metrics (records synced, latency percentiles, error counts), structured JSON logs with correlation IDs, and distributed traces for debugging ([$[Connector Framework — Module Overview]$]).

3. **Audit logs**: All connector configuration changes are recorded with user identity, timestamp, before/after state diff, source IP, and user agent. Audit logs are retained for 12 months ([$[DPLAT-REQ-05]$]).

4. **Health check API**: You can query connector health programmatically via `GET /api/v1/connectors/{id}/health` and sync metrics via `GET /api/v1/connectors/{id}/metrics?window=1h` ([$[Connector Operations Runbook]$]).

The status read API maintains **99.9% availability** with p95 latency under 500ms and p99 under 1000ms, supporting up to 1000 requests per second per tenant ([$[DPLAT-REQ-05]$], [$[DPLAT-REQ-14]$]).

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)

## Compliance Check

### How to View Connector Health Status

For compliance purposes, connector health status is viewed through the **Health Monitor dashboard**, which provides a unified, real-time view of all connectors in your tenant. According to [$[DPLAT-007]$], the dashboard displays a table listing all connectors (Salesforce, SAP S/4) with columns for **Name**, **Status** (Green/Yellow/Red), **Last Sync Time**, and **Error Count**. 

The status colors are automatically calculated based on compliance-relevant thresholds:
- **Green** = successful sync in the last 1 hour
- **Yellow** = warning state or sync 1–6 hours ago
- **Red** = failed sync or no activity in the last 6 hours

Workspace admins can filter the table by Status and search by connector name, with filters persisting across page reloads. Clicking on a connector row navigates to a detailed view showing the last 100 audit log entries for that specific data source, where PII-tagged fields are masked for non-compliance-officer users (per [$[DPLAT-007]$] QA verification).

For programmatic compliance checks, the health status read API is available at `GET /api/v1/connectors/{id}/health` (per the [$[Connector Operations Runbook]$]), with a 99.9% uptime SLA and p95 response time under 200ms (per [$[DPLAT-REQ-05]$]).

### How to Configure Alerts for Connectivity Issues

Alerting is configured via the Health Monitor's alerting system, which supports **PagerDuty** and **email** notifications (per [$[DPLAT-008]$]). For compliance monitoring, the following alert types are available (per the [$[Release Notes — v2.4 (Planned)]$]):

| Alert Type | Description | Severity |
|------------|-------------|----------|
| Connection Failure | Connector unable to reach data source | Critical |
| Sync Degradation | Latency exceeding threshold | Warning |
| Schema Drift | Upstream schema change detected | Warning |
| Rate Limit Exhaustion | API throttling detected | Info |

**Configuration** is done via YAML in workspace settings:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

For compliance-specific alerting, the severity mapping is: HTTP 5xx errors = Critical, HTTP 4xx = Warning, timeouts = Critical (per [$[DPLAT-008]$] comments). Alerts are deduplicated so repeated failures of the same connector within a 15-minute window do not create duplicate incidents.

### Where Health Metrics Are Stored

Health metrics are stored in two locations for compliance purposes:

1. **Datadog** — The Health Monitor exports connector status, latency, and error rate metrics every 60 seconds to Datadog via a StatsD exporter (per [$[DPLAT-027]$]). Exported metrics include tags for tenant, workspace, connector type, and data source name. This enables correlation of data pipeline health with application performance for compliance reporting.

2. **Historical metrics storage** — The Connector Health Monitor epic ([$[DPLAT-EPIC-03]$]) specifies storage and retrieval of historical health metrics for trend analysis, including uptime percentage, average latency, and error frequency. This supports compliance audit trails and trend analysis.

For compliance officers, the **audit log** (accessible via the dashboard detail view) retains entries for 12 months (per [$[DPLAT-REQ-05]$]), and the [$[Connector Operations Runbook]$] provides a retention audit endpoint: `GET /api/v1/retention/violations?tenant={id}` for investigating retention policy violations.

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
