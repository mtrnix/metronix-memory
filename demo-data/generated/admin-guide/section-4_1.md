# 4.1  Scheduled exports

> Automating regular audit log delivery.

## Schedule Setup

### How to Schedule an Audit Log Export

To schedule an audit log export, a workspace admin can configure the export schedule through the **Compliance Vault settings UI**. According to [$[DPLAT-009]$], the scheduling is implemented using **cron-based jobs** that automate the export process. The admin can set the export to run on a **daily, weekly, or monthly** basis.

The scheduled export generates a **CSV file** containing all audit log fields (timestamp, user, action, resource_type, resource_id, outcome, and session_id) and saves it to a **customer-managed S3 bucket** with date-based naming (`audit-log-YYYY-MM-DD.csv`).

### How to Change Export Frequency

To change the export frequency, the workspace admin can modify the schedule directly in the Compliance Vault settings UI. The available options are:
- **Daily**
- **Weekly**
- **Monthly**

The system uses cron-based scheduling, so changing the frequency updates the cron job configuration accordingly.

### Where to See Scheduled Tasks

Scheduled export job status can be monitored in two places:

1. **Connector Health Monitor Dashboard** — Per [$[DPLAT-043]$], the Health Monitor displays an "Audit Log Export" panel showing the most recent job status (Success, In Progress, Failed, or Not Run), along with the timestamp of the last export attempt. The panel refreshes automatically every 30 seconds and uses color-coded indicators (green=Success, yellow=In Progress, red=Failed, gray=Not Run).

2. **Export Queue Status Page** — The system maintains an export queue where job statuses can be tracked. Note that per [$[DPLAT-DEF-18]$], there is a known bug where queuing 4 or more exports simultaneously can cause a deadlock, with jobs stuck in "Processing" status. The workaround is to manually cancel queued exports and re-submit them one at a time with 30-second intervals.

### Key Implementation Details

- **Retry Logic**: Failed exports are retried up to 3 times with exponential backoff, and the workspace admin receives a notification email on permanent failure (per [$[DPLAT-009]$]).
- **Export Format**: Currently, scheduled exports produce CSV files. Additional formats (Parquet, JSON-NDJSON) are available for ad-hoc exports per [$[DPLAT-040]$], but the scheduled export feature specifically targets CSV output to S3.
- **Security**: Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with access logged to the immutable audit trail (per [$[DPLAT-REQ-08]$]).

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Frequency

To schedule an audit export, you configure the export schedule through the **Compliance Vault settings UI** as a workspace admin. According to [$[DPLAT-009]$], the scheduled export feature allows you to set the export frequency to **daily, weekly, or monthly**. The export job runs automatically at the scheduled time and generates a file with date-based naming (e.g., `audit-log-YYYY-MM-DD.csv`).

### How to Change Export Frequency

You can change the export frequency directly in the Compliance Vault settings UI. The available options are:
- **Daily** — exports every 24 hours
- **Weekly** — exports once per week
- **Monthly** — exports once per month

The scheduled export is implemented using **cron-based jobs** (per [$[DPLAT-009]$] comment by dev2), so changing the frequency updates the underlying cron schedule.

### Where to See Scheduled Tasks

You can monitor scheduled export job status in the **Connector Health Monitor dashboard**. According to [$[DPLAT-043]$], the Health Monitor displays an "Audit Log Export" panel showing:
- Most recent export job status (Success, In Progress, Failed, or Not Run)
- Timestamp of the last export attempt
- A link to view the full audit log export history

The panel refreshes automatically every 30 seconds and uses color-coded status indicators (green=Success, yellow=In Progress, red=Failed, gray=Not Run).

**Note:** The current epic scope ([$[DPLAT-EPIC-05]$]) explicitly states that automated scheduled exports are **out of scope** for the initial phase, which focuses on manual ad-hoc exports only. The scheduled export capability described above is implemented specifically in [$[DPLAT-009]$], which is marked as **Done** and targets the v2.2 release.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Timezones

To schedule an audit log export, workspace administrators configure a cron-based job through the Compliance Vault settings UI, as implemented in [$[DPLAT-009]$]. The export schedule supports daily, weekly, or monthly frequency, and exports are delivered as CSV files to a target S3 bucket with date-based naming (e.g., `audit-log-YYYY-MM-DD.csv`).

### Timezone Impact on Scheduled Exports

The **Timezone** aspect is critical for scheduled exports because of a known bug documented in [$[DPLAT-DEF-05]$]. When a user with a non-UTC timezone (e.g., America/New_York, Europe/Berlin) configures an ad-hoc date range export, the system incorrectly applies the user's timezone offset as a simple addition to UTC timestamps, rather than performing proper timezone-aware date boundary calculations. For example, an EST (UTC-5) user selecting "2026-03-15 to 2026-03-20" receives logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC", effectively missing the first 5 hours and including 5 extra hours of data.

**Expected behavior** (per [$[DPLAT-DEF-05]$]): The system should interpret user-selected date ranges in the user's local timezone and correctly convert to UTC. Selecting "2026-03-15 to 2026-03-20" as an EST user should return all logs from "2026-03-15 00:00:00 UTC to 2026-03-21 04:59:59 UTC" (full calendar days in the user's local time).

### Where to See Scheduled Tasks

Scheduled export job status can be monitored in two places:
1. **Health Monitor Dashboard** — As implemented in [$[DPLAT-043]$], the Connector Health Monitor displays an "Audit Log Export" panel showing the most recent export job status (Success, In Progress, Failed, or Not Run) with the timestamp of the last attempt. This panel refreshes automatically every 30 seconds.
2. **Export Queue Status Page** — For viewing all queued exports, though note a known deadlock issue ([$[DPLAT-DEF-18]$]) where 4+ simultaneous exports can stall in "Processing" status.

### Workaround for Timezone Issues

Until the timezone bug is fixed (currently In Progress, assigned to dev2@amisol-demo.example), users should either manually adjust date ranges by adding/subtracting their timezone offset hours, or perform exports while logged in with a UTC timezone account, as noted in [$[DPLAT-DEF-05]$].

**Sources:**
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)

## Destination Config

To schedule an audit log export, you configure the destination and frequency through the Compliance Vault settings UI. According to [$[DPLAT-009]$], workspace administrators can set up scheduled CSV exports to an S3 bucket for off-platform compliance backups. The destination configuration involves specifying the target S3 bucket where exported files will be stored.

### How to Schedule an Export

1. Navigate to **Compliance Vault → Audit Log → Export** in the settings UI
2. Configure the **destination**: specify the target S3 bucket (IAM role authentication is used for S3 integration, per [$[DPLAT-009]$])
3. Set the **export schedule**: choose from daily, weekly, or monthly frequency options
4. The system generates files with date-based naming: `audit-log-YYYY-MM-DD.csv`

### Changing Export Frequency

You can modify the export frequency (daily/weekly/monthly) directly in the Compliance Vault settings UI where the scheduled export is configured. The schedule uses cron-based job scheduling, as noted in [$[DPLAT-009]$].

### Where to See Scheduled Tasks

Scheduled export job status is visible in two places:

1. **Health Monitor Dashboard** — per [$[DPLAT-043]$], the Connector Health Monitor includes an "Audit Log Export" panel showing the most recent job status (Success, In Progress, Failed, or Not Run) with color-coded indicators (green/yellow/red/gray). This panel refreshes automatically every 30 seconds and includes a link to view full export history.

2. **Export Queue Status Page** — accessible from Compliance Vault → Audit Log → Export, where you can monitor queued and processing jobs.

### Important Notes

- Only **workspace administrators** can configure scheduled exports (per [$[DPLAT-009]$] acceptance criteria)
- Failed exports are retried up to 3 times with exponential backoff, with notification emails on permanent failure
- A known bug ([$[DPLAT-DEF-18]$]) causes deadlocks when 4+ exports are queued simultaneously — the workaround is to submit exports one at a time with 30-second intervals

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Trigger Logic

The "Scheduled exports" feature in the Compliance Vault is designed for **automated, recurring export of audit logs** to a customer-managed S3 bucket, as implemented in [$[DPLAT-009]$]. The trigger logic is based on a **cron-based scheduling system** that workspace administrators configure through the Compliance Vault settings UI.

### How to Schedule an Audit Export

To schedule an audit export, a workspace admin navigates to the **Compliance Vault settings UI** and configures the following parameters (per [$[DPLAT-009]$]):
- **Export schedule**: Choose from daily, weekly, or monthly frequency
- **Target S3 bucket**: Specify the destination bucket for the exported CSV files
- The system then uses **cron-based jobs** to automatically trigger the export at the configured time

The exported CSV files follow a date-based naming convention: `audit-log-YYYY-MM-DD.csv`, and include all audit log fields: timestamp, user, action, resource_type, resource_id, outcome, and session_id.

### How to Change Export Frequency

To change the export frequency, a workspace admin returns to the **Compliance Vault settings UI** and modifies the schedule selection (daily/weekly/monthly). The cron-based job system updates the trigger accordingly. Note that only workspace admins have the permissions to configure scheduled exports — compliance officers can only trigger **ad-hoc exports** with date ranges (per [$[DPLAT-010]$]).

### Where to See Scheduled Tasks

Scheduled export job status is visible in two places:
1. **Connector Health Monitor Dashboard** — As implemented in [$[DPLAT-043]$], the Health Monitor displays an "Audit Log Export" panel showing the most recent export job status (Success, In Progress, Failed, or Not Run), the timestamp of the last attempt, and a link to view full export history. This panel refreshes automatically every 30 seconds.
2. **Export Queue Status Page** — For monitoring active and queued exports (note: a known bug [$[DPLAT-DEF-18]$] causes deadlocks when 4+ exports are queued simultaneously, requiring manual intervention via the admin console).

### Trigger Logic Summary

The trigger logic is **time-based (cron)**, not event-driven. The system runs the export job automatically at the configured schedule time. Failed exports are retried up to 3 times with exponential backoff, and the workspace admin receives a notification email on permanent failure. The export feature is designed for **historical point-in-time exports only** — real-time streaming and automated scheduled exports were explicitly out of scope for the initial epic ([$[DPLAT-EPIC-05]$]).

**Sources:**
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Export Parameters

### How to Schedule an Audit Export

To schedule an audit export, a **workspace admin** configures the export through the Compliance Vault settings UI. According to [$[DPLAT-009]$], the scheduling parameters include:

- **Frequency**: Choose from daily, weekly, or monthly export intervals
- **Target Destination**: Specify an S3 bucket for the exported files
- **File Naming**: Exports are automatically named using the pattern `audit-log-YYYY-MM-DD.csv`
- **Retry Logic**: Failed exports are automatically retried up to 3 times with exponential backoff

The scheduled export is implemented using cron-based jobs, and the S3 integration uses IAM role authentication for secure access (per [$[DPLAT-009]$] implementation notes).

### How to Change Export Frequency

To change the export frequency, a workspace admin navigates to the Compliance Vault settings UI and modifies the schedule configuration. The available options are:

- **Daily** — generates one export file per day
- **Weekly** — generates one export file per week
- **Monthly** — generates one export file per month

The frequency setting is part of the export configuration that can be updated at any time through the UI. Note that the export format defaults to CSV, but as of v2.3, compliance officers can also select Parquet or JSON-NDJSON formats via a dropdown selector when initiating exports (per [$[DPLAT-040]$]).

### Where to See Scheduled Tasks

Scheduled export job status can be monitored in two places:

1. **Health Monitor Dashboard** — As implemented in [$[DPLAT-043]$], the Connector Health Monitor displays an "Audit Log Export" panel showing the most recent export job status (Success, In Progress, Failed, or Not Run). The panel includes:
   - Timestamp of the last export attempt
   - A link to view the full audit log export history
   - Color-coded status indicators (green=Success, yellow=In Progress, red=Failed, gray=Not Run)
   - Auto-refresh every 30 seconds

2. **Export Queue Status Page** — For viewing all queued and in-progress export jobs. Note that there is a known issue ([$[DPLAT-DEF-18]$]) where the export job queue can deadlock if 4 or more exports are queued simultaneously, causing jobs to remain in "Processing" status indefinitely. The workaround is to submit exports one at a time with 30-second intervals.

### Export Parameters Summary

| Parameter | Details | Source |
|-----------|---------|--------|
| **Frequency** | Daily, Weekly, Monthly | [$[DPLAT-009]$] |
| **Target** | S3 bucket (IAM role auth) | [$[DPLAT-009]$] |
| **Format** | CSV (default), Parquet, JSON-NDJSON | [$[DPLAT-040]$] |
| **File Naming** | `audit-log-YYYY-MM-DD.csv` | [$[DPLAT-009]$] |
| **Retry** | Up to 3 retries with exponential backoff | [$[DPLAT-009]$] |
| **Access Control** | Only workspace-admin can configure schedules; compliance-officer role can trigger ad-hoc exports | [$[DPLAT-REQ-10]$] |
| **Monitoring** | Health Monitor dashboard + Export Queue page | [$[DPLAT-043]$] |

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)

## Data Range

For the **Scheduled exports** feature, the **Data Range** aspect is handled differently than for ad-hoc exports. Based on the available sources, here is what you need to know:

### How to Schedule an Audit Export

According to [$[DPLAT-009]$], workspace administrators can configure scheduled CSV exports of audit logs to an S3 bucket via the Compliance Vault settings UI. The scheduled export generates a complete CSV file with date-based naming (`audit-log-YYYY-MM-DD.csv`) — it exports **all** audit log records accumulated up to the scheduled run time, not a filtered date range.

### How to Change Export Frequency

Per [$[DPLAT-009]$], the export schedule can be configured with three frequency options:
- **Daily**
- **Weekly**
- **Monthly**

These options are available in the Compliance Vault settings UI where the workspace admin configures the export. The export job runs automatically at the scheduled time using cron-based jobs (as noted in the implementation comment by dev2).

### Where to See Scheduled Tasks

The scheduled export jobs run in the background via cron-based job scheduling (per [$[DPLAT-009]$] implementation notes). The system includes:
- Automatic retry (up to 3 times with exponential backoff) for failed exports
- Notification emails to workspace admins on permanent failure
- The export queue status page (referenced in [$[DPLAT-DEF-18]$]) where you can monitor export job status

### Important: Data Range Limitation

**Key distinction**: The scheduled export feature ([$[DPLAT-009]$]) does **not** support configurable date ranges. It exports the full accumulated audit log up to the scheduled time. Date range filtering is only available for **ad-hoc exports** ([$[DPLAT-010]$]), where compliance officers can specify start and end dates. This is explicitly noted in the [$[DPLAT-EPIC-05]$] epic scope, which states that automated scheduled exports are out of scope for the initial phase.

If you need to export audit logs for a specific date range, you must use the ad-hoc export feature rather than the scheduled export.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)

## Format Selection

To schedule an audit export, a workspace admin configures the export through the Compliance Vault settings UI. The key aspect of **Format Selection** is that when initiating an export, you see a dropdown with exactly three format options: **CSV, Parquet, and JSON-NDJSON**, with CSV set as the default selection [$[DPLAT-040]$].

### How Format Selection Works in Scheduled Exports

Based on the available sources, the scheduled export feature (implemented in [$[DPLAT-009]$]) currently supports **CSV format** for automated exports to S3 buckets. The exported CSV includes all audit log fields: timestamp, user, action, resource_type, resource_id, outcome, and session_id, with date-based naming (audit-log-YYYY-MM-DD.csv).

However, the format selector story [$[DPLAT-040]$] (status: Done, fix version v2.3) adds the ability to choose between all three formats (CSV, Parquet, JSON-NDJSON) for exports. This selector is available when initiating an export, though it's worth noting that the scheduled export feature in [$[DPLAT-009]$] specifically mentions CSV format for the automated S3 bucket export.

### Changing Export Frequency

To change export frequency, the workspace admin configures the schedule in the Compliance Vault settings UI, where the available options are **daily, weekly, or monthly** [$[DPLAT-009]$]. The export job runs automatically at the scheduled time.

### Viewing Scheduled Tasks

You can see the status of scheduled export jobs in two places:

1. **Health Monitor Dashboard**: The Connector Health Monitor (F-A3) includes an "Audit Log Export" panel showing the most recent export job status (Success, In Progress, Failed, or Not Run), along with the timestamp of the last export attempt and a link to view the full export history [$[DPLAT-043]$]. This panel refreshes automatically every 30 seconds.

2. **Export Queue Status Page**: For monitoring active exports, there is an Export Queue status page within the Compliance Vault module. Note that there is a known bug ([$[DPLAT-DEF-18]$]) where the export job queue can deadlock if 4 or more exports are queued simultaneously, causing jobs to remain in "Processing" status indefinitely. The workaround is to submit exports one at a time with 30-second intervals.

### Format-Specific Details

- **CSV**: Produces files with proper headers, correctly escaped special characters, and UTF-8 encoding [$[DPLAT-040]$]
- **Parquet**: Produces valid Apache Parquet files with proper schema metadata, typed columns, and row group compression (~60% compression ratio per testing) [$[DPLAT-040]$]
- **JSON-NDJSON**: Produces files where each line contains a single valid JSON object, with no trailing commas or array wrappers [$[DPLAT-040]$]

**Sources:**
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)

## Filter Criteria

To schedule an audit export, you configure the export via the Compliance Vault settings UI. According to [$[DPLAT-009]$], a workspace admin can set up a scheduled CSV export to an S3 bucket with configurable frequency (daily, weekly, or monthly). The export job runs automatically at the scheduled time and generates a file with date-based naming (`audit-log-YYYY-MM-DD.csv`).

### How Filter Criteria Works

The filter criteria for scheduled exports is defined through the **Audit Log Query Language (DSL)** documented in [$[Audit Log — Query Language Reference]$]. When configuring a scheduled export, you specify filter expressions that determine which audit events are included. The key filter components are:

- **Event Type**: Filter by action category (e.g., `event_type=data_export`)
- **Time Range**: Use relative syntax like `timestamp:[NOW-30d TO NOW]` for the last 30 days, or absolute ISO-8601 ranges
- **Actor/Role**: Filter by user identity (`actor_id`) or role (`actor_role`)
- **Resource Path**: Target specific resources (`resource_path`)
- **Custom Metadata**: Use dot notation for nested fields (e.g., `metadata.pii_fields IN (email, ssn)`)

For scheduled exports specifically, the time-range filter is typically set to a relative window (e.g., last 24 hours for daily exports) so each run captures only new events since the last export.

### Changing Export Frequency

To change the export frequency, you modify the schedule configuration in the Compliance Vault settings UI. Per [$[DPLAT-009]$], the available options are **daily, weekly, or monthly**. The system uses cron-based jobs to execute exports at the configured interval.

### Viewing Scheduled Tasks

Scheduled export tasks can be monitored via the **Export Queue status page** in the Compliance Vault UI. However, note a known issue: per [$[DPLAT-DEF-18]$], the export job queue can deadlock if 4 or more exports are queued simultaneously, causing jobs to remain in "Processing" status indefinitely. The workaround is to manually cancel queued exports and re-submit them one at a time with 30-second intervals.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Volume Limits

### How to Schedule an Audit Export

According to [JIRA] [$[DPLAT-009]$], workspace administrators can configure scheduled CSV exports of audit logs to an S3 bucket through the Compliance Vault settings UI. The export schedule supports daily, weekly, or monthly frequency options. The export job runs automatically at the configured time and generates files with date-based naming (e.g., `audit-log-YYYY-MM-DD.csv`). Failed exports are retried up to 3 times with exponential backoff, and the workspace admin receives a notification email on permanent failure.

### How to Change Export Frequency

To change the export frequency, a workspace admin navigates to the Compliance Vault settings UI and adjusts the schedule configuration (daily/weekly/monthly) as described in [$[DPLAT-009]$]. The system uses cron-based jobs to manage the scheduling, as noted by the assignee in the implementation comments.

### Where to See Scheduled Tasks

Scheduled export job status can be viewed in two places:
1. **Health Monitor Dashboard**: Per [$[DPLAT-043]$], the Connector Health Monitor includes an "Audit Log Export" panel showing the most recent job status (Success, In Progress, Failed, or Not Run), the timestamp of the last attempt, and a link to the full export history. The panel refreshes automatically every 30 seconds with color-coded indicators (green=Success, yellow=In Progress, red=Failed, gray=Not Run).
2. **Compliance Vault UI**: The export history can be accessed directly within the Compliance Vault module.

### Volume Limits Aspect

The "Volume Limits" consideration for scheduled exports is addressed by the following constraints from the knowledge base:

- **Export Size Constraint**: Per [$[DPLAT-REQ-08]$], a full 90-day export of audit logs must fit within **4 GB compressed CSV** per tenant. This is a hard size limit for scheduled exports.
- **Event Volume**: According to [$[ADR-007]$], the audit log handles up to **500K events/hour at peak** (~400MB/hour raw). For scheduled exports, this means a daily export could theoretically cover up to 12 million events, but the 4 GB compressed limit effectively caps the exportable volume.
- **Retention Policy**: The audit log retains data for **2555 days** (7 years) per the [$[audit-log-service]$] configuration, but scheduled exports are typically configured for shorter intervals (daily/weekly/monthly) to stay within the 4 GB limit.
- **Query Limitations**: Per the [$[Audit Log Query Language Reference]$], individual queries are capped at **100,000 events maximum**, though scheduled exports likely bypass this limit by using batch processing.

**Key Takeaway**: When scheduling exports, ensure the selected frequency and date range produce a compressed CSV under 4 GB. For high-volume tenants (approaching 500K events/hour), a daily export is recommended to avoid exceeding the volume limit. The system's retry mechanism (3 retries with exponential backoff) helps ensure export completion even under high load conditions.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)

## Monitoring & Alerts

### How to Schedule an Audit Log Export

According to [$[DPLAT-009]$], workspace administrators can configure scheduled CSV exports of audit logs to an S3 bucket through the Compliance Vault settings UI. The scheduling options include **daily, weekly, or monthly** intervals. The export generates files with date-based naming (`audit-log-YYYY-MM-DD.csv`) and includes all audit log fields: timestamp, user, action, resource_type, resource_id, outcome, and session_id.

### How to Change Export Frequency

To change the export frequency, navigate to the Compliance Vault settings UI where the schedule configuration is located. The available options are **daily, weekly, or monthly** (per [$[DPLAT-009]$]). Note that the current implementation (v2.2) supports these three presets; custom cron expressions are not mentioned in the available documentation.

### Where to See Scheduled Tasks

The **Health Monitor dashboard** (implemented in [$[DPLAT-043]$]) provides a centralized view of export job status. Specifically:

- A dedicated **"Audit Log Export" panel** displays the most recent job status: **Success** (green), **In Progress** (yellow), **Failed** (red), or **Not Run** (gray)
- The panel shows the **timestamp of the last export attempt** and includes a **link to view full export history**
- The panel **auto-refreshes every 30 seconds**, consistent with other Health Monitor indicators

### Monitoring & Alerts Specifics

For the "Monitoring & Alerts" aspect, the following mechanisms are in place:

1. **Failure Notifications**: Per [$[DPLAT-009]$], failed exports are retried up to 3 times with exponential backoff. On permanent failure, the workspace admin receives a **notification email**.

2. **Health Monitor Integration**: The export job status is visible alongside connector health indicators in the Health Monitor dashboard ([$[DPLAT-043]$]), allowing correlation between connector health and compliance export completion.

3. **Known Issue**: There is a **known deadlock bug** ([$[DPLAT-DEF-18]$]) where 4+ simultaneous export jobs can stall in "Processing" status indefinitely. The workaround is to manually cancel queued exports and re-submit with 30-second intervals. This bug is currently **In Progress** for a fix.

4. **Export Format Options**: As of v2.3 ([$[DPLAT-040]$]), exports support **CSV, Parquet, or JSON-NDJSON** formats, with CSV as the default. Parquet achieves ~60% compression ratio.

5. **Security & Integrity**: Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with access logged to the immutable audit trail ([$[DPLAT-REQ-08]$], [$[DPLAT-REQ-10]$]). A future enhancement ([$[DPLAT-014]$], v2.4) will add encrypted archives with signed manifests for non-repudiation.

**Key Takeaway for Monitoring**: The Health Monitor dashboard is your primary monitoring tool for scheduled exports. Check the "Audit Log Export" panel for job status, and ensure you have email notifications configured for failure alerts. Be aware of the deadlock issue when planning multiple concurrent exports.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Job Status

To schedule an audit log export, a workspace admin configures the export schedule (daily, weekly, or monthly) and target S3 bucket via the Compliance Vault settings UI, as described in [$[DPLAT-009]$]. The export runs automatically at the scheduled time using cron-based jobs and generates a CSV file with date-based naming (e.g., `audit-log-YYYY-MM-DD.csv`). Failed exports are retried up to 3 times with exponential backoff, and the admin receives a notification email on permanent failure.

**Changing export frequency** is done through the same Compliance Vault settings UI where the schedule (daily/weekly/monthly) is configured.

**Where to see scheduled tasks and their status**: The Health Monitor dashboard (introduced in [$[DPLAT-043]$]) displays a dedicated "Audit Log Export" panel that shows the most recent export job status. The panel uses color-coded indicators:
- **Green** = Success
- **Yellow** = In Progress
- **Red** = Failed
- **Gray** = Not Run

The panel includes the timestamp of the last export attempt and a link to view the full export history. It refreshes automatically every 30 seconds, consistent with other Health Monitor panels.

**Important caveat regarding job status**: A known bug ([$[DPLAT-DEF-18]$]) causes the export job queue to deadlock when 4 or more exports are queued simultaneously. In this state, all jobs remain in "Processing" status indefinitely. The workaround is to manually cancel queued exports, restart the export service, and re-submit exports one at a time with 30-second intervals. This issue is currently being fixed.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)

## Failure Notifications

To schedule an audit export, a workspace admin configures the export via the Compliance Vault settings UI, where they can set the schedule (daily, weekly, or monthly) and specify the target S3 bucket [$[DPLAT-009]$]. The export job runs automatically at the scheduled time using cron-based jobs and generates a file with date-based naming (e.g., `audit-log-YYYY-MM-DD.csv`).

### Changing Export Frequency

You can change the export frequency directly in the Compliance Vault settings UI by selecting from the available schedule options: daily, weekly, or monthly [$[DPLAT-009]$]. This is configured during the initial setup and can be modified at any time by a workspace admin.

### Viewing Scheduled Tasks

Scheduled export job status can be viewed in two places:
1. **Health Monitor Dashboard** — The "Audit Log Export" panel shows the most recent export job status (Success, In Progress, Failed, or Not Run) with color-coded indicators and the timestamp of the last attempt. This panel refreshes automatically every 30 seconds [$[DPLAT-043]$].
2. **Export Queue Status Page** — For a detailed view of all queued and completed exports [$[DPLAT-DEF-18]$].

### Failure Notifications

The failure notification system works as follows:

- **Retry Logic**: If a scheduled export fails, the system automatically retries up to **3 times** with exponential backoff [$[DPLAT-009]$].
- **Notification on Permanent Failure**: After all retries are exhausted and the export still fails, the workspace admin receives a **notification email** informing them of the permanent failure [$[DPLAT-009]$].
- **Status Visibility**: The Health Monitor dashboard shows a red "Failed" status indicator for failed exports, allowing quick identification of issues [$[DPLAT-043]$].
- **Known Issue**: Note that there is a known bug where queuing 4 or more exports simultaneously can cause a deadlock, leaving jobs stuck in "Processing" status indefinitely. The workaround is to cancel queued exports, restart the service, and submit exports one at a time with 30-second intervals [$[DPLAT-DEF-18]$].

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)

## Success Logs

### How to Schedule an Audit Export

To schedule an audit export, a **workspace-admin** configures the export through the **Compliance Vault settings UI** ([$[DPLAT-009]$]). The scheduled export generates CSV files of audit logs and sends them to a customer-managed S3 bucket. The export job runs automatically at the configured time using **cron-based jobs** with IAM role authentication for S3 integration.

The exported CSV includes all audit log fields: timestamp, user, action, resource_type, resource_id, outcome, and session_id. Files are named using the pattern `audit-log-YYYY-MM-DD.csv`.

### How to Change Export Frequency

The export schedule supports three frequency options: **daily, weekly, or monthly** ([$[DPLAT-009]$]). The workspace admin selects the desired frequency when configuring the export in the Compliance Vault settings UI. There is no mention of a custom frequency option in the provided sources.

### Where to See Scheduled Tasks

The **Health Monitor dashboard** includes an "Audit Log Export" panel that displays the status of the most recent export job ([$[DPLAT-043]$]). This panel shows:

- **Status indicators**: Green (Success), Yellow (In Progress), Red (Failed), Gray (Not Run)
- **Timestamp** of the last export attempt
- A **link** to view the full audit log export history

The panel refreshes automatically every 30 seconds, consistent with other Health Monitor panels.

### Success Logs Aspect

For the "Success Logs" subsection specifically:

- **Successful exports** are indicated by a **green status** in the Health Monitor dashboard panel ([$[DPLAT-043]$]).
- The export operation logs its own **success/failure status** in the Compliance Vault audit trail ([$[DPLAT-015]$]).
- Failed exports are **retried up to 3 times** with exponential backoff, and the workspace admin receives a **notification email** on permanent failure ([$[DPLAT-009]$]).
- The export pipeline must achieve **99.9% success rate** with automatic retry on transient failures ([$[DPLAT-REQ-08]$]).

**Note**: There is a known bug ([$[DPLAT-DEF-18]$]) where the export job queue can deadlock if 4 or more exports are queued simultaneously, causing jobs to remain in "Processing" status indefinitely. The workaround is to manually cancel queued exports, restart the service, and re-submit exports one at a time with 30-second intervals. This bug is currently **In Progress** and may affect success logs if multiple exports are triggered concurrently.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)

## Retries

To schedule an audit export, a workspace admin configures the export schedule (daily, weekly, or monthly) and target S3 bucket via the Compliance Vault settings UI, as described in [$[DPLAT-009]$]. The export job runs automatically at the scheduled time and generates a file with date-based naming (e.g., `audit-log-YYYY-MM-DD.csv`).

### Changing Export Frequency

The export frequency can be changed by modifying the schedule configuration in the Compliance Vault settings UI. The available options are daily, weekly, or monthly (per [$[DPLAT-009]$]).

### Viewing Scheduled Tasks

Scheduled export job status can be viewed in the Connector Health Monitor dashboard, which displays a dedicated "Audit Log Export" panel showing the most recent job status (Success, In Progress, Failed, or Not Run) along with the timestamp of the last attempt and a link to the full export history (per [$[DPLAT-043]$]).

### Retries — Key Details

The retry mechanism for scheduled exports is specifically defined in [$[DPLAT-009]$]:

1. **Retry Count**: Failed exports are retried **up to 3 times**.
2. **Backoff Strategy**: Retries use **exponential backoff** between attempts.
3. **Permanent Failure Notification**: If all 3 retries fail, the workspace admin receives a **notification email** about the permanent failure.

This retry logic was verified during QA testing (per comment by dev1 on [$[DPLAT-009]$]: "Verified retry logic works correctly").

Additionally, for ad-hoc exports (not scheduled), the system also supports retry capability for failed transmissions, as noted in [$[DPLAT-015]$] (ServiceNow integration), with the caveat that the retry mechanism should respect the tenant's retention policy to avoid holding failed exports indefinitely.

**Important note**: The scheduled export feature (including its retry logic) is currently **out of scope** for the initial phase of the Audit Log Export epic ([$[DPLAT-EPIC-05]$]), which focuses on manual ad-hoc exports only. The scheduled export with retries was implemented separately in [$[DPLAT-009]$] and is already marked as **Done** in version v2.2.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Audit & Security

### How to Schedule an Audit Export

To schedule an audit export for compliance and security purposes, a **workspace admin** can configure a recurring CSV export of audit logs to a customer-managed S3 bucket through the Compliance Vault settings UI. This is implemented in [$[DPLAT-009]$], which provides the following capabilities:

- **Schedule options**: Daily, weekly, or monthly export frequency
- **Target destination**: Customer-specified S3 bucket
- **File naming**: Auto-generated with date-based format (`audit-log-YYYY-MM-DD.csv`)
- **Retry mechanism**: Failed exports are retried up to 3 times with exponential backoff
- **Notifications**: Workspace admin receives an email notification on permanent failure

The exported CSV includes all audit log fields: timestamp, user, action, resource_type, resource_id, outcome, and session_id.

### Changing Export Frequency

The export frequency can be modified directly in the Compliance Vault settings UI. The available options are **daily, weekly, or monthly**. There is no mention of custom intervals beyond these three presets in the current implementation.

### Where to See Scheduled Tasks

Scheduled export job status can be monitored in two places:

1. **Connector Health Monitor Dashboard** — As implemented in [$[DPLAT-043]$], a dedicated "Audit Log Export" panel displays the most recent job status (Success, In Progress, Failed, or Not Run) with color-coded indicators (green/yellow/red/gray). The panel refreshes automatically every 30 seconds and includes a link to view the full export history.

2. **Export Queue Status Page** — For monitoring multiple queued exports, though note a known issue: [$[DPLAT-DEF-18]$] reports that the export job queue can deadlock if 4 or more exports are queued simultaneously. The current workaround is to submit exports one at a time with 30-second intervals.

### Audit & Security Considerations

From a security perspective, the scheduled export feature is governed by **Role-Based Access Control (RBAC)** — per [$[DPLAT-REQ-10]$], only users with the **Compliance Officer** role can trigger exports. All authorization decisions are logged to the immutable audit trail. Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with access logged to the audit trail.

For enhanced security in future releases, [$[DPLAT-014]$] (currently In Progress) will add encrypted archive format with AES-256-GCM encryption and RSA-signed manifests for non-repudiation, allowing compliance officers to securely share audit trails with external auditors.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Task Creation Audit

### How to Schedule an Audit Export

To schedule an audit export for the Task Creation Audit, a **workspace admin** configures the export through the **Compliance Vault settings UI** (per [$[DPLAT-009]$]). The scheduled export generates a CSV file and sends it to a customer-managed **S3 bucket**. The exported CSV includes all audit log fields: timestamp, user, action, resource_type, resource_id, outcome, and session_id — which covers task creation events.

The export job runs automatically at the configured time and produces files with date-based naming (e.g., `audit-log-YYYY-MM-DD.csv`). If an export fails, the system retries up to **3 times with exponential backoff**, and the workspace admin receives a notification email on permanent failure.

**Note:** The initial phase of the Audit Log Export epic ([$[DPLAT-EPIC-05]$]) explicitly states that automated scheduled exports are **out of scope** — only manual ad-hoc exports were planned initially. However, [$[DPLAT-009]$] (status: Done, fix version v2.2) has already implemented the scheduled export capability, so it is now available.

### How to Change Export Frequency

The export schedule is configurable with three options: **daily, weekly, or monthly** (per [$[DPLAT-009]$]). A workspace admin can change the frequency by updating the schedule settings in the Compliance Vault UI. There is no mention of custom cron expressions or hourly intervals — only these three preset frequencies are supported.

### Where to See Scheduled Tasks

You can monitor scheduled export job status in two places:

1. **Health Monitor Dashboard** — The [$[DPLAT-043]$] feature adds an "Audit Log Export" panel to the Connector Health Monitor dashboard. This panel shows the most recent export job status (Success, In Progress, Failed, or Not Run), the timestamp of the last attempt, and a link to the full export history. It refreshes automatically every 30 seconds.

2. **Export Queue Status Page** — The Compliance Vault module has an Export Queue status page where you can see queued and processing jobs. Note that a known bug ([$[DPLAT-DEF-18]$]) causes a deadlock if **4 or more exports are queued simultaneously** — jobs stall in "Processing" status. The workaround is to cancel all queued exports, restart the export service, and re-submit exports one at a time with 30-second intervals.

### Task Creation Audit Specifics

For the Task Creation Audit use case, the scheduled export captures all audit log entries — including task creation events — in the CSV output. The export includes the `action` field (which would record "task_created" or similar), along with the user who performed the action, the timestamp, and the resource ID of the created task. This allows you to audit task creation activity over time without manual intervention.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)

## Access Control

To schedule an audit export, you must have the **Compliance Officer** role. According to [JIRA] [$[DPLAT-REQ-10]$], only users with the Compliance Officer role can trigger audit log exports. This is enforced through Role-Based Access Control (RBAC) that logs all authorization decisions to the immutable audit trail.

### How to Schedule an Export

1. Navigate to **Compliance Vault → Audit Log → Export** in the UI.
2. Configure the export schedule (daily, weekly, or monthly) and specify the target S3 bucket.
3. The system uses cron-based jobs to run the export automatically at the scheduled time, generating a file named `audit-log-YYYY-MM-DD.csv` (per [JIRA] [$[DPLAT-009]$]).

**Access Control Note**: The export feature is restricted to Compliance Officers only. Workspace admins cannot trigger exports directly, though they can view export job status in the Health Monitor dashboard (see below).

### Changing Export Frequency

You can modify the export frequency (daily/weekly/monthly) through the Compliance Vault settings UI. This is configured per the acceptance criteria in [JIRA] [$[DPLAT-009]$]. The system uses cron-based scheduling, so changing the frequency updates the cron expression accordingly.

### Where to See Scheduled Tasks

Scheduled export jobs and their status are visible in two places:

1. **Compliance Vault Export Queue** – Shows all queued, processing, and completed exports. Note: there is a known bug ([JIRA] [$[DPLAT-DEF-18]$]) where 4+ queued exports can cause a deadlock, so monitor this page carefully.

2. **Connector Health Monitor Dashboard** – Per [JIRA] [$[DPLAT-043]$], workspace admins can see an "Audit Log Export" panel showing the most recent job status (Success, In Progress, Failed, or Not Run) with color-coded indicators. This panel refreshes every 30 seconds and includes a link to the full export history.

### Security Requirements

All exported files must be encrypted at rest using AES-256 and in transit using TLS 1.3 (per [JIRA] [$[DPLAT-REQ-10]$]). Additionally, [JIRA] [$[DPLAT-014]$] (currently in progress) will add encrypted archive format with signed manifests for v2.4.

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)

## Encryption

To schedule an audit export with encryption, you use the Compliance Vault's export scheduling feature. According to [$[DPLAT-009]$], a workspace admin can configure a scheduled CSV export to an S3 bucket with a daily, weekly, or monthly frequency via the Compliance Vault settings UI. However, the encryption aspect is specifically addressed in [$[DPLAT-014]$], which is currently **In Progress** and targets the v2.4 release.

### How to Schedule an Encrypted Export

The encrypted export feature ([$[DPLAT-014]$]) generates a **.zip archive** containing the audit log CSV and a `manifest.json` file, with the **entire archive encrypted using AES-256-GCM**. The process works as follows:

1. **Archive Encryption**: The export produces a .zip archive encrypted with AES-256-GCM.
2. **Signed Manifest**: The `manifest.json` includes a SHA-256 hash of the audit log CSV, export timestamp, tenant identifier, and an RSA-2048 digital signature.
3. **Password Derivation**: The decryption password is derived from a user-provided passphrase using **PBKDF2 with at least 100,000 iterations**. A password hint is displayed during export configuration.
4. **Verification Tool**: After export completion, a "Verify Export" button appears, allowing the compliance officer to validate the manifest signature and confirm archive integrity **without decryption**.

### Changing Export Frequency

To change the export frequency, you configure the schedule (daily/weekly/monthly) in the Compliance Vault settings UI, as described in [$[DPLAT-009]$]. The encrypted export feature ([$[DPLAT-014]$]) does not currently specify its own scheduling mechanism, so it would likely inherit the scheduling configuration from the base export functionality.

### Where to See Scheduled Tasks

Scheduled export job status can be monitored in two places:

1. **Health Monitor Dashboard**: Per [$[DPLAT-043]$], the Connector Health Monitor displays an "Audit Log Export" panel showing the most recent export job status (Success, In Progress, Failed, or Not Run), the timestamp of the last attempt, and a link to view full export history. This panel refreshes automatically every 30 seconds.
2. **Export Queue**: The export job queue (mentioned in [$[DPLAT-DEF-18]$]) shows queued and processing exports, though note that a known bug causes deadlocks when 4+ exports are queued simultaneously.

### Encryption-Specific Considerations

- **Encryption-at-Rest**: The audit log storage itself supports encryption-at-rest with tenant-managed keys (BYOK) using AES-256-GCM, as specified in [$[DPLAT-REQ-19]$]. This is separate from the export encryption but ensures stored logs are encrypted.
- **Key Management**: The BYOK feature ([$[DPLAT-REQ-19]$]) provides REST endpoints for workspace admins to upload, rotate, and retire tenant encryption keys, with automatic key rotation configurable (default: 90 days).
- **Current Limitation**: The encrypted export feature ([$[DPLAT-014]$]) is still **In Progress** and not yet available in production. The current scheduled export ([$[DPLAT-009]$]) produces plaintext CSV files without encryption.

**Sources:**
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)

## Logs

### How to Schedule an Audit Export

To schedule an audit log export, a **workspace admin** navigates to the **Compliance Vault → Audit Log → Export** section in the settings UI. There, they can configure a recurring export to a customer-managed S3 bucket. The export generates a CSV file named `audit-log-YYYY-MM-DD.csv` containing all audit log fields: timestamp, user, action, resource_type, resource_id, outcome, and session_id. The scheduled export uses cron-based jobs with IAM role authentication for S3 integration (per [$[DPLAT-009]$]).

**Important:** Only users with the **Compliance Officer** role can trigger exports (per [$[DPLAT-REQ-10]$]). Workspace admins can configure the schedule, but the actual export initiation is role-restricted.

### How to Change Export Frequency

The export schedule supports three frequency options: **daily**, **weekly**, or **monthly**. You can change the frequency by returning to the Compliance Vault settings UI and selecting a new schedule from the dropdown. The system automatically adjusts the cron job to match the new frequency. If you need to change the target S3 bucket, that can also be updated in the same settings panel.

### Where to See Scheduled Tasks

Scheduled export job status is visible in two places:

1. **Connector Health Monitor Dashboard** – A dedicated "Audit Log Export" panel shows the most recent job status (Success, In Progress, Failed, or Not Run) with color-coded indicators (green/yellow/red/gray). It includes the timestamp of the last attempt and a link to view full export history. The panel refreshes automatically every 30 seconds (per [$[DPLAT-043]$]).

2. **Export Queue Status Page** – Located under Compliance Vault → Audit Log → Export, this page shows all queued and running export jobs. **Note:** There is a known bug where queuing 4 or more exports simultaneously can cause a deadlock, leaving jobs stuck in "Processing" status. The workaround is to submit exports one at a time with 30-second intervals (per [$[DPLAT-DEF-18]$]).

### Logs-Specific Considerations

- **Retention:** Audit logs are retained for **2555 days** (7 years) by default, configurable via the `AUDIT_RETENTION_DAYS` environment variable (per [$[audit-log-service]$]).
- **Format:** Exports default to CSV but support Parquet and JSON-NDJSON formats via a format selector dropdown (per [$[DPLAT-040]$]).
- **Security:** Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with access logged to the immutable audit trail (per [$[DPLAT-REQ-08]$]).
- **Timezone Bug:** When scheduling exports, be aware of a known issue where non-UTC users' date ranges are shifted by their timezone offset. For example, an EST user selecting "2026-03-15 to 2026-03-20" will get logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC" instead of the full calendar days. The workaround is to manually adjust the date range or use a UTC timezone account (per [$[DPLAT-DEF-05]$]).

**Sources:**
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
