# 4.2  Ad-hoc exports

> Manual extraction of audit data for investigations.

## Export Execution

To perform a manual (ad-hoc) export of audit logs in the Compliance Vault, follow these steps:

1. **Navigate to the Export Page**: As a compliance officer with appropriate permissions, go to the Compliance Vault → Audit Log Export section. You will see a form with start date, end date, and export format options ([$[DPLAT-010]$]).

2. **Set the Date Range**: Select a custom date range using the start and end date fields. **Important**: The system interprets dates in your local timezone. If you are in a non-UTC timezone (e.g., America/New_York), the export window may be shifted by your offset. For example, an EST user selecting "2026-03-15 to 2026-03-20" will receive logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC", potentially missing the first 5 hours of each day. The workaround is to manually adjust the range or use a UTC account ([$[DPLAT-DEF-05]$]).

3. **Choose Export Format**: Select from three formats: **CSV** (default), **Parquet**, or **JSON-NDJSON**. CSV includes proper headers and UTF-8 encoding; Parquet provides ~60% compression with typed columns; JSON-NDJSON outputs one valid JSON object per line ([$[DPLAT-040]$]).

4. **Submit the Export**: Click the export button. The system generates the file and sends you a notification email with a secure download link that expires after **24 hours** ([$[DPLAT-010]$]).

5. **Download the File**: Use the link to download the exported audit log, which includes fields like timestamp, user, action, data source, and affected PII fields.

### Filtering Ad-Hoc Reports

You can filter exports by date range (as described above). Additional filtering options include:
- **Event type** (e.g., `data_export`, `login`)
- **Actor role** (e.g., `admin`, `compliance-officer`)
- **Resource path**, **connector ID**, **tenant ID**, and **custom metadata** (e.g., `metadata.pii_fields IN (email, ssn)`)
- **Time-range syntax** supports both absolute ISO-8601 ranges and relative shortcuts like `-30d` for the last 30 days ([$[Audit Log — Query Language Reference]$]).

### Limits on Manual Exports

- **Queue Deadlock**: If 4 or more export jobs are queued simultaneously, the system may enter a deadlock state, leaving jobs stuck in "Processing" indefinitely. The workaround is to cancel all queued exports, restart the export service, and submit exports one at a time with 30-second intervals ([$[DPLAT-DEF-18]$]).
- **Query Limits**: Maximum 100,000 events per query; regex matches limited to 100-byte patterns; aggregations capped at 1,000 distinct groups ([$[Audit Log — Query Language Reference]$]).
- **Retention Policy**: Queries older than the tenant's retention policy return empty results. The default PII retention is 30 days ([$[PII Auto-Tagging — Policy and Behavior]$]).
- **Export Generation**: Expected latency under 5 seconds for datasets up to 10,000 records ([$[DPLAT-EPIC-05]$]).

**Note**: The export feature is currently manual only; scheduled exports are out of scope for this phase ([$[DPLAT-EPIC-05]$]).

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)

## Query Builder

### How to Perform a Manual Export

To perform a manual export using the Query Builder, a compliance officer navigates to the Audit Log Export page in the Compliance Vault UI. The process involves:

1. **Selecting a date range**: The form provides start and end date fields. You can use absolute ISO-8601 timestamps (e.g., `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative shortcuts like `-7d` for the last 7 days or `-30d` for the last 30 days (per [$[Audit Log — Query Language Reference]$]).

2. **Applying filters**: Use the query DSL to narrow results. For example, to see all export activity in the last month, enter: `event_type=data_export AND timestamp:[NOW-30d TO NOW]`. You can combine filters with logical operators (`AND`, `OR`, `NOT`) and comparison operators (`=`, `!=`, `>`, `<`, `~` for regex, `IN` for set membership).

3. **Choosing an export format**: Select from CSV (default), Parquet, or JSON-NDJSON via a dropdown (per [$[DPLAT-040]$]).

4. **Submitting the request**: The system generates a CSV (or chosen format) file containing all matching audit log entries, including timestamp, user, action, data source, and affected PII fields. Upon completion, you receive a notification email with a secure download link that expires after 24 hours (per [$[DPLAT-010]$]).

### How to Filter Ad-hoc Reports

The Query Builder supports filtering through its domain-specific query language. Key filtering capabilities include:

- **By event type**: `event_type=data_export`
- **By actor role**: `actor_role=admin`
- **By data volume**: `bytes_transferred>5000000`
- **By timestamp**: Absolute ranges (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative (`timestamp:[NOW-30d TO NOW]`)
- **By nested metadata**: `metadata.source=connector-crm-001` or `metadata.pii_fields IN (email, ssn, phone)`
- **Combined filters**: `event_type=data_export AND actor_role=admin AND bytes_transferred>5000000`

You can also apply aggregations to summarize results, such as `AGGREGATE: count BY actor_role` or `AGGREGATE: SUM(bytes_transferred) BY event_type`.

### Limits on Manual Exports

The following limits apply to manual exports via the Query Builder:

- **Maximum events per query**: 100,000 events (per [$[Audit Log — Query Language Reference]$])
- **Regex pattern length**: Limited to 100-byte patterns
- **Aggregation groups**: Capped at 1,000 distinct groups
- **Retention policy**: Queries older than the tenant's retention policy return empty results
- **Export job queue**: A known bug ([$[DPLAT-DEF-18]$]) can cause a deadlock if 4 or more exports are queued simultaneously. Workaround: submit exports one at a time with 30-second intervals.
- **Timezone offset issue**: A known bug ([$[DPLAT-DEF-05]$]) causes date ranges to be misinterpreted for non-UTC users. For example, an EST user selecting "2026-03-15 to 2026-03-20" receives logs shifted by -5 hours. Workaround: manually adjust the date range or use a UTC timezone account.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)

## Filter Application

### How to Perform a Manual Export

To perform a manual (ad-hoc) export of audit logs, a compliance officer navigates to the Compliance Vault → Audit Log Export page. There, they see a form with **start date**, **end date**, and **export format** options (CSV, Parquet, or JSON-NDJSON, with CSV as default) per [$[DPLAT-010]$] and [$[DPLAT-040]$]. After selecting the desired date range and format, the officer submits the request. The system generates a CSV (or chosen format) file containing all audit log entries within the specified range, including timestamp, user, action, data source, and affected PII fields. Upon completion, the officer receives a notification email with a secure download link that expires after 24 hours.

### How to Filter Ad-hoc Reports

The **Filter Application** for ad-hoc exports is primarily date-range based. The export form allows the compliance officer to specify a **customizable date range** (start and end dates) to retrieve historical records for external audits or regulatory reviews. According to [$[DPLAT-010]$], the export includes all audit log entries within the specified range. Additionally, the Audit Log Query Language Reference describes a broader filtering DSL that supports filtering by event type, actor identity, resource path, and custom metadata using comparison and logical operators (e.g., `event_type=data_export AND actor_role=admin`), though the ad-hoc export UI currently focuses on date range filtering. Future capabilities (in v2.4) will add full-text search across historical exports per [$[DPLAT-037]$].

### Limits on Manual Exports

The following limits apply to manual exports:

- **Maximum 100,000 events per query** — as stated in the Audit Log Query Language Reference.
- **Export job queue deadlock** — if 4 or more export jobs are queued simultaneously, the system can deadlock, leaving jobs stuck in "Processing" status indefinitely. The workaround is to cancel all queued exports, restart the export service, and re-submit exports one at a time with 30-second intervals per [$[DPLAT-DEF-18]$].
- **Timezone offset bug** — for non-UTC users, the date range selection is incorrectly shifted by the user's timezone offset, potentially missing or including extra hours of data. The workaround is to manually adjust the date range or use a UTC account per [$[DPLAT-DEF-05]$].
- **Export generation latency** — targeted under 5 seconds for datasets up to 10,000 records per [$[DPLAT-EPIC-05]$].
- **Secure download link** — expires after 24 hours per [$[DPLAT-010]$].

### Focus on Filter Application

For the **Filter Application** aspect specifically, the primary filter available for manual exports is the **date range filter** (start and end dates). This is the core mechanism for narrowing down the audit log entries to be exported. The system does not currently support advanced filtering (by user, data source, event type) in the ad-hoc export UI — those are planned for future releases or available through the query DSL for other purposes. The date range filter is applied at the backend to query the audit log storage, and the export includes all matching entries within that range.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)

## Format Selection

To perform a manual export of audit logs, a compliance officer navigates to the Audit Log Export page in the Compliance Vault. According to [$[DPLAT-010]$], the export form includes start date, end date, and export format options. The system then generates a CSV file containing all audit log entries within the specified range, including timestamp, user, action, data source, and affected PII fields. Upon completion, the officer receives a notification email with a secure download link that expires after 24 hours.

### Format Selection Options

Per [$[DPLAT-040]$], when initiating an audit log export, the compliance officer sees a dropdown with exactly three format options:

- **CSV** (default selection) — Produces a file with proper headers, correctly escaped special characters (commas, quotes, newlines), and UTF-8 encoding.
- **Parquet** — Produces a valid Apache Parquet file with proper schema metadata, typed columns, and row group compression (compression ratio ~60%).
- **JSON-NDJSON** — Produces a file where each line contains a single valid JSON object representing one audit log entry, with no trailing commas or array wrappers.

### Filtering Ad-hoc Reports

To filter ad-hoc reports, the compliance officer can configure a date range (start and end dates) on the export form. Additionally, the Audit Log Query Language Reference (per [$[Audit Log — Query Language Reference]$]) supports advanced filtering by event type, actor identity, resource path, and custom metadata using comparison operators (e.g., `=`, `!=`, `>`, `<`, `~` for regex) and logical operators (`AND`, `OR`, `NOT`). Time ranges can be specified as absolute ISO-8601 timestamps or relative shortcuts (e.g., `-30d` for last 30 days).

### Limits on Manual Exports

Based on the available context, the following limits apply to manual exports:

- **Export generation latency**: Under 5 seconds for datasets up to 10,000 records (per [$[DPLAT-EPIC-05]$]).
- **Query limits**: Maximum 100,000 events per query; regex matches limited to 100-byte patterns; aggregations capped at 1,000 distinct groups (per [$[Audit Log — Query Language Reference]$]).
- **Export queue**: A known bug ([$[DPLAT-DEF-18]$]) causes deadlock when 4 or more export jobs are queued simultaneously. The workaround is to submit exports one at a time with 30-second intervals.
- **Timezone issue**: A known bug ([$[DPLAT-DEF-05]$]) causes date range shifts for non-UTC users. The workaround is to manually adjust the date range or use a UTC account.
- **Download link**: Exported files are delivered via secure download links that expire after 24 hours (per [$[DPLAT-010]$]).

**Note**: Scheduled exports (e.g., to S3 buckets) are a separate feature ([$[DPLAT-009]$]) and are not part of the manual ad-hoc export workflow.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)

## Export Trigger

### How to Perform a Manual Export

To trigger a manual (ad-hoc) export of audit logs, a **compliance officer** navigates to the **Audit Log Export** page within the Compliance Vault module. There, they see a form with the following fields:

- **Start date** and **End date** — to define the date range for the export
- **Export format** — a dropdown with three options: **CSV** (default), **Parquet**, and **JSON-NDJSON** (per [$[DPLAT-040]$])

After submitting the request, the system generates the export file and sends a **notification email** with a **secure download link** that expires after **24 hours** (per [$[DPLAT-010]$]).

### How to Filter Ad-hoc Reports

The primary filter available for ad-hoc exports is the **date range** — you specify a start and end date to retrieve only audit log entries within that period. According to [$[DPLAT-010]$], the exported CSV includes: timestamp, user, action, data source, and affected PII fields.

**Important caveat regarding timezone filtering**: There is a known bug ([$[DPLAT-DEF-05]$]) where the date range filter incorrectly applies the user's timezone offset. For example, a user in EST (UTC-5) selecting "2026-03-15 to 2026-03-20" receives logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC" — effectively shifting the window. The expected behavior is that the system should interpret dates in the user's local timezone and convert to UTC correctly. The workaround is to manually adjust the date range or perform the export while logged in with a UTC timezone account.

### Limits on Manual Exports

1. **Export queue limit**: If **4 or more** export jobs are queued simultaneously, the export job queue can **deadlock**, causing all jobs to remain in "Processing" status indefinitely and blocking subsequent requests ([$[DPLAT-DEF-18]$]). The workaround is to cancel all queued exports, restart the export service, and re-submit exports one at a time with 30-second intervals.

2. **Performance target**: Export generation should complete in **under 5 seconds** for datasets up to **10,000 records** (per [$[DPLAT-EPIC-05]$]).

3. **Download link expiration**: The secure download link expires after **24 hours** ([$[DPLAT-010]$]).

4. **Format-specific**: CSV, Parquet, and JSON-NDJSON formats are supported, with Parquet achieving approximately **60% compression** ratio ([$[DPLAT-040]$]).

**Note**: Scheduled exports are out of scope for this phase — only manual initiation is supported ([$[DPLAT-EPIC-05]$]).

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-017] Salesforce — bulk migration tool from legacy v1 connector](https://demo-jira.local/browse/DPLAT-017)

## Data Scope

### How to Perform a Manual Export

Based on the available documentation, a compliance officer can trigger a manual (ad-hoc) export of audit logs through the Compliance Vault UI or API. The process involves:

1. **Navigate** to the Audit Log Export page in the Compliance Vault module (per [$[DPLAT-010]$]).
2. **Select a date range** — the form includes start date and end date fields (per [$[DPLAT-010]$]).
3. **Choose an export format** — a dropdown offers three options: CSV (default), Parquet, and JSON-NDJSON (per [$[DPLAT-040]$]).
4. **Submit the request** — the system generates the export file and sends a notification email with a secure download link that expires after 24 hours (per [$[DPLAT-010]$]).

The export can also be triggered programmatically via the `/api/v1/compliance/audit-query` endpoint using the query DSL (per [$[Audit Log — Query Language Reference]$]).

### How to Filter Ad-hoc Reports

Filters are applied using the Compliance Vault's domain-specific query language (DSL). Key filtering capabilities relevant to data scope include:

- **Time-range filters**: Use absolute ISO-8601 timestamps (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative ranges (`timestamp:[NOW-30d TO NOW]`) (per [$[Audit Log — Query Language Reference]$]).
- **Event type filtering**: Filter by action category, e.g., `event_type=data_export` (per [$[Audit Log — Query Language Reference]$]).
- **Actor and resource filters**: Filter by `actor_id`, `actor_role`, `resource_path`, `connector_id`, and `tenant_id` (per [$[Audit Log — Query Language Reference]$]).
- **PII-specific filtering**: Use `metadata.pii_sensitive=true` or `metadata.pii_fields IN (email, ssn, phone)` to scope exports to sensitive data access (per [$[Audit Log — Query Language Reference]$]).
- **Logical combinations**: Combine filters with `AND`, `OR`, and `NOT` operators (per [$[Audit Log — Query Language Reference]$]).

**Important caveat**: There is a known timezone bug ([$[DPLAT-DEF-05]$]) where non-UTC users' date range selections are incorrectly shifted by their timezone offset. The workaround is to manually adjust the range or use a UTC account.

### Limits on Manual Exports

The following limits apply to the data scope of manual exports:

| Limit | Value | Source |
|-------|-------|--------|
| Maximum events per query | 100,000 records | [$[Audit Log — Query Language Reference]$] |
| Export generation latency target | Under 5 seconds for ≤10,000 records; under 30 seconds for ≤100,000 records | [$[DPLAT-EPIC-05]$], [$[DPLAT-REQ-10]$] |
| Concurrent export requests | Up to 5 compliance officers without degradation | [$[DPLAT-REQ-10]$] |
| Secure download link expiry | 24 hours | [$[DPLAT-010]$] |
| Encryption | AES-256 at rest, TLS 1.3 in transit | [$[DPLAT-REQ-10]$] |
| Retention policy | Queries older than tenant retention policy return empty results | [$[Audit Log — Query Language Reference]$] |
| Aggregation limits | Capped at 1,000 distinct groups | [$[Audit Log — Query Language Reference]$] |
| Regex pattern limit | Maximum 100-byte patterns | [$[Audit Log — Query Language Reference]$] |

**Data scope specifics**: The export includes the full audit trail as recorded — timestamp, user, action, data source, and affected PII fields (per [$[DPLAT-010]$]). PII field masking is applied based on tenant configuration during CSV generation (per [$[DPLAT-010]$] comments). The underlying storage uses Postgres with row-level security for multi-tenant isolation (per [$[ADR-007]$]), meaning exports are automatically scoped to the requesting compliance officer's tenant context.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)

## Time Range

### How to Perform a Manual Export

To perform a manual (ad-hoc) export of audit logs with a time range filter, a compliance officer navigates to the Audit Log Export page where they see a form with **start date**, **end date**, and **export format** options (per [$[DPLAT-010]$]). The export is triggered by submitting the date range request, and the system generates a CSV file (or Parquet/JSON-NDJSON, per [$[DPLAT-040]$]) containing all audit log entries within the specified range, including timestamp, user, action, data source, and affected PII fields. Upon completion, the compliance officer receives a notification email with a secure download link that expires after 24 hours.

The query DSL supports both **absolute** and **relative** time ranges (per [$[Audit Log — Query Language Reference]$]):

- **Absolute ranges**: Use ISO-8601 timestamps with inclusive bounds, e.g., `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`
- **Relative ranges**: Use shortcuts like `-7d` (last 7 days), `-30d` (last 30 days), `-90d` (last 90 days), or `-1y` (last year), e.g., `timestamp:[NOW-30d TO NOW]`

### How to Filter Ad-hoc Reports

The time range is the primary filter for ad-hoc exports. Additional filtering can be applied using the audit log query DSL, which supports filter expressions combining field names, operators, and values (per [$[Audit Log — Query Language Reference]$]). For example:

```
event_type=data_export AND timestamp:[NOW-30d TO NOW]
```

Available filter fields include `event_type`, `actor_id`, `actor_role`, `resource_path`, `ip_address`, `http_status`, `bytes_transferred`, `connector_id`, `tenant_id`, and `session_id`. Logical operators (`AND`, `OR`, `NOT`) and comparison operators (`=`, `!=`, `>`, `<`, `>=`, `<=`, `~` for regex, `IN` for set membership) are supported.

### Limits on Manual Exports

Based on the available sources, the following limits apply to manual exports:

- **Maximum 100,000 events per query** (per [$[Audit Log — Query Language Reference]$])
- **Export operation must complete within 30 seconds for datasets up to 100,000 log entries** (per [$[DPLAT-REQ-10]$])
- **Concurrent export requests**: Up to 5 compliance officers can trigger exports simultaneously without degradation (per [$[DPLAT-REQ-10]$])
- **Export job queue deadlock**: A known bug ([$[DPLAT-DEF-18]$]) causes deadlock when 4+ exports are queued simultaneously — the workaround is to submit exports one at a time with 30-second intervals
- **Queries older than tenant retention policy return empty results** (per [$[Audit Log — Query Language Reference]$])

### Time Range-Specific Considerations

A critical time range issue is documented in [$[DPLAT-DEF-05]$]: when a user with a non-UTC timezone (e.g., America/New_York, Europe/Berlin) performs an ad-hoc date range export, the exported records are **shifted by the user's timezone offset**. For example, an EST (UTC-5) user selecting "2026-03-15 to 2026-03-20" receives logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC", effectively missing the first 5 hours and including 5 extra hours of data. The expected behavior is that user-selected date ranges should be interpreted in the user's local timezone and correctly converted to UTC. This bug is currently **In Progress** with a workaround of manually adjusting the date range or performing the export while logged in with a UTC timezone account.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)

## User Filtering

### How to Perform a Manual Export

To perform a manual (ad-hoc) export of audit logs, a compliance officer navigates to the Compliance Vault → Audit Log → Export page. There, they fill out a form with a **start date**, **end date**, and select an **export format** (CSV, Parquet, or JSON-NDJSON) [$[DPLAT-010]$]. Upon submission, the system generates a file containing all audit log entries within the specified range, including timestamp, user, action, data source, and affected PII fields. The user receives a notification email with a secure download link that expires after 24 hours [$[DPLAT-010]$].

### How to Filter Ad-hoc Reports (User Filtering)

For user-specific filtering, the system uses a domain-specific query language (DSL) that supports filtering by **actor identity** and other fields [$[Audit Log — Query Language Reference]$]. The key field for user filtering is:

- **`actor_id`** — User or service identifier (string type)

You can apply user filtering using comparison operators:

```
actor_id=jane.doe@company.com
```

Or combine with other filters using logical operators:

```
event_type=data_export AND actor_id=jane.doe@company.com AND timestamp:[NOW-30d TO NOW]
```

The query language also supports set membership for filtering multiple users:

```
actor_id IN (jane.doe@company.com, john.smith@company.com)
```

Additionally, you can filter by **`actor_role`** to narrow results by role (e.g., `actor_role=admin`), and by **`resource_path`** to target specific data sources [$[Audit Log — Query Language Reference]$].

### Limits on Manual Exports

The following limits apply to manual exports and queries:

| Limit | Value |
|-------|-------|
| Maximum events per query | **100,000 events** |
| Regex pattern length | **100 bytes** maximum |
| Aggregation groups | **1,000 distinct groups** maximum |
| Export job queue | **Deadlock risk if 4+ exports queued simultaneously** (bug DPLAT-DEF-18) |
| Download link expiry | **24 hours** after generation |

**Important known issue**: When a user with a non-UTC timezone (e.g., America/New_York) performs an ad-hoc export, the date range is incorrectly shifted by the user's timezone offset [$[DPLAT-DEF-05]$]. For example, an EST user selecting "2026-03-15 to 2026-03-20" receives logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC" instead of the full calendar days. The workaround is to manually adjust the date range or use a UTC timezone account [$[DPLAT-DEF-05]$].

Additionally, if 4 or more export jobs are queued simultaneously, the system may enter a deadlock state where all jobs remain in "Processing" status indefinitely [$[DPLAT-DEF-18]$]. The workaround is to cancel queued exports, restart the export service, and re-submit exports one at a time with 30-second intervals.

**Sources:**
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)

## Event Type

### How to Perform a Manual Export

To perform a manual export of audit logs, a compliance officer navigates to the Audit Log Export page in the Compliance Vault UI. According to [$[DPLAT-010]$], the export form includes start date, end date, and export format options. The system generates a CSV file containing all audit log entries within the specified range, including timestamp, user, action, data source, and affected PII fields. Upon completion, the officer receives a notification email with a secure download link that expires after 24 hours.

### How to Filter Ad-hoc Reports by Event Type

To filter ad-hoc exports specifically by **Event Type**, you use the Compliance Vault's query DSL. Per the [$[Audit Log — Query Language Reference]$], the `event_type` field supports exact match, set membership, and regex operators. For example:

- **Exact match**: `event_type=data_export`
- **Multiple event types**: `event_type IN (login, logout, data_export)`
- **Combined with date range**: `event_type=data_export AND timestamp:[NOW-30d TO NOW]`

You can also combine event type filters with other fields like `actor_role`, `bytes_transferred`, or `resource_path` using logical operators (`AND`, `OR`, `NOT`). For instance, to find admin-initiated data exports over 5MB: `event_type=data_export AND actor_role=admin AND bytes_transferred>5000000`.

### Limits on Manual Exports

The following limits apply to manual exports (based on the [$[Audit Log — Query Language Reference]$]):

- **Maximum events per query**: 100,000 events
- **Regex pattern length**: Limited to 100-byte patterns
- **Aggregation groups**: Capped at 1,000 distinct groups
- **Retention policy**: Queries older than the tenant's retention policy return empty results

Additionally, there is a known issue with the export job queue: per [$[DPLAT-DEF-18]$], if 4 or more export jobs are queued simultaneously, the system can deadlock, leaving jobs stuck in "Processing" status. The workaround is to submit exports one at a time with 30-second intervals.

**Important note on timezone handling**: Per [$[DPLAT-DEF-05]$], there is a known bug where non-UTC users' date range selections are not properly converted to UTC. For example, an EST user selecting "2026-03-15 to 2026-03-20" receives logs shifted by -5 hours. The workaround is to manually adjust the date range or perform exports while logged in with a UTC timezone account.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)

## Granularity

### How to Perform a Manual Export

To perform a manual (ad-hoc) export of audit logs, a compliance officer navigates to the **Compliance Vault → Audit Log Export** page. There, they see a form with **start date**, **end date**, and **export format** options (CSV, Parquet, or JSON-NDJSON, with CSV as default per [$[DPLAT-040]$]). After selecting the date range and format, the officer submits the request. The system generates the export file and sends a notification email with a **secure download link that expires after 24 hours** (per [$[DPLAT-010]$]).

### How to Filter Ad-hoc Reports

Ad-hoc exports can be filtered primarily by **date range** (start and end dates). However, the underlying query language (documented in [$[Audit Log — Query Language Reference]$]) supports much richer filtering for the export itself:

- **Event type**: e.g., `event_type=data_export`
- **Actor identity**: e.g., `actor_id=user123`
- **Actor role**: e.g., `actor_role=admin`
- **Resource path**: e.g., `resource_path=/connectors/crm`
- **Custom metadata**: e.g., `metadata.pii_fields IN (email, ssn)`
- **Time range**: absolute ISO-8601 ranges or relative shortcuts like `-30d`

These filters can be combined using logical operators (`AND`, `OR`, `NOT`). The export feature uses the existing audit log storage with a filtering layer for date ranges (per [$[DPLAT-010]$]).

### Limits on Manual Exports

Based on the query language reference and related tickets, the following limits apply:

| Limit | Value | Source |
|-------|-------|--------|
| **Maximum events per query** | 100,000 events | [$[Audit Log — Query Language Reference]$] |
| **Export completion time** | Must complete within 30 seconds for datasets up to 100,000 entries | [$[DPLAT-REQ-10]$] |
| **Concurrent exports** | Support up to 5 concurrent compliance officers without degradation | [$[DPLAT-REQ-10]$] |
| **Queue deadlock** | 4+ simultaneous exports can cause deadlock (bug DPLAT-DEF-18, workaround: submit exports 30 seconds apart) | [$[DPLAT-DEF-18]$] |
| **Download link expiry** | 24 hours | [$[DPLAT-010]$] |
| **Retry on failure** | Up to 3 retries with exponential backoff (for scheduled exports; ad-hoc may differ) | [$[DPLAT-009]$] |
| **Timezone offset bug** | Non-UTC users may experience shifted date ranges (bug DPLAT-DEF-05, workaround: manually adjust or use UTC account) | [$[DPLAT-DEF-05]$] |

### Granularity Considerations

The **granularity** of manual exports is primarily determined by the **date range** selected. The system interprets user-selected dates in the user's local timezone and converts to UTC for the backend query. However, due to the known bug [$[DPLAT-DEF-05]$], this conversion is currently incorrect for non-UTC users — the offset is applied as a simple addition rather than proper timezone-aware date boundary calculations. This means a user in EST selecting "2026-03-15 to 2026-03-20" would receive logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC", missing the first 5 hours and including 5 extra hours.

For finer granularity, compliance officers can use the query DSL's time-range syntax with absolute ISO-8601 timestamps (e.g., `timestamp:[2026-03-15T08:00:00Z TO 2026-03-15T17:00:00Z]`) to narrow exports to specific hours or minutes. The export format selector (CSV, Parquet, JSON-NDJSON) does not affect granularity but affects how the data is structured for downstream tools.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)

## Permissions & Access

### How do I perform a manual export?

To perform a manual (ad-hoc) export of audit logs, you must have the **Compliance Officer** role. According to [$[DPLAT-REQ-10]$], only users with this role can trigger exports. The process is:

1. Navigate to the **Compliance Vault → Audit Logs** section.
2. Use the export form to specify a **start date** and **end date** for the date range you want to export.
3. Select an **export format** from the dropdown — options are CSV (default), Parquet, or JSON-NDJSON, as documented in [$[DPLAT-040]$].
4. Submit the export request. The system generates the file and sends a **notification email** with a secure download link that expires after **24 hours** (per [$[DPLAT-010]$]).

**Important timezone consideration**: Per [$[DPLAT-DEF-05]$], there is a known bug where users with non-UTC timezones (e.g., America/New_York) may experience a timezone offset shift in exported records. The workaround is to manually adjust the date range or perform the export while logged in with a UTC timezone account.

### How can I filter ad-hoc reports?

The Compliance Vault provides a domain-specific query language (DSL) for filtering audit log events, documented in [$[Audit Log — Query Language Reference]$]. Key filtering capabilities include:

- **Comparison operators**: `=` (exact match), `!=`, `>`, `<`, `>=`, `<=`, `~` (regex), and `IN` (set membership)
- **Logical operators**: Combine filters with `AND`, `OR`, and `NOT`
- **Time-range syntax**: Use absolute ISO-8601 ranges (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative shortcuts (`-7d`, `-30d`, `-90d`, `-1y`)
- **Available fields**: Filter by `event_type`, `actor_id`, `actor_role`, `resource_path`, `ip_address`, `http_status`, `bytes_transferred`, `connector_id`, `tenant_id`, and nested metadata fields

For example, to filter for export activity in the last 30 days: `event_type=data_export AND timestamp:[NOW-30d TO NOW]`

### What are the limits on manual exports?

Based on the available sources, the following limits apply to manual exports:

- **Maximum events per query**: 100,000 events (per [$[Audit Log — Query Language Reference]$])
- **Export performance**: The export operation must complete within **30 seconds** for datasets up to 100,000 log entries (per [$[DPLAT-REQ-10]$])
- **Concurrent users**: Supports up to **5 compliance officers** running concurrent exports without degradation (per [$[DPLAT-REQ-10]$])
- **Security**: Exported files are encrypted at rest using **AES-256** and in transit using **TLS 1.3** (per [$[DPLAT-REQ-10]$])
- **Download link expiration**: Secure download links expire after **24 hours** (per [$[DPLAT-010]$])
- **Retention policy**: Queries older than the tenant's retention policy return empty results (per [$[Audit Log — Query Language Reference]$])

### Access Control Summary

The export functionality is strictly gated by **Role-Based Access Control (RBAC)** — only users with the **Compliance Officer** role can trigger ad-hoc exports. All authorization decisions are logged to the immutable audit trail for compliance purposes (per [$[DPLAT-REQ-10]$]).

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)

## Role Requirements

Based on the provided context, here is the information for the 'Ad-hoc exports' section, specifically focused on the 'Role Requirements' aspect.

To perform a manual (ad-hoc) export of audit logs, you must have the **compliance-officer** role. This is a core requirement, as the feature is specifically designed for this role to retrieve historical records for external audits or regulatory reviews [JIRA DPLAT-010]. The workspace-admin role is associated with scheduled exports, not manual ones [JIRA DPLAT-009].

The process for a compliance officer is as follows:
1.  Navigate to the Audit Log Export page within the Compliance Vault.
2.  Use the provided form to specify a date range (start and end date) and select an export format (CSV, Parquet, or JSON-NDJSON) [JIRA DPLAT-010, DPLAT-040].
3.  Submit the request. The system will generate the file and send a notification email with a secure download link that expires after 24 hours [JIRA DPLAT-010].

**Filtering ad-hoc reports** is done by specifying the date range. The system also supports advanced filtering by user, data source, connector, and event type to support targeted compliance reviews [JIRA DPLAT-EPIC-05].

**Limits on manual exports** for a compliance officer include:
- A maximum of 100,000 events per query [CONFLUENCE Audit Log — Query Language Reference].
- A known bug where the export job queue can deadlock if 4 or more exports are queued simultaneously [JIRA DPLAT-DEF-18].
- A known bug where the date range filter incorrectly applies the user's timezone offset, which could lead to missing critical events in the export [JIRA DPLAT-DEF-05].

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)

## Export Authorization

### How to Perform a Manual Export

As a compliance officer, you can trigger an ad-hoc export of the audit log by navigating to the Audit Log Export page in the Compliance Vault. The export form requires you to specify a **start date** and **end date** for the date range, and you can select the export format from a dropdown with three options: **CSV** (default), **Parquet**, or **JSON-NDJSON** (per [$[DPLAT-040]$]).

Once you submit the request, the system generates the export file containing all audit log entries within the specified range, including timestamp, user, action, data source, and affected PII fields. When the export completes, you receive a notification email with a **secure download link that expires after 24 hours** (per [$[DPLAT-010]$]).

**Important timezone consideration:** If your user profile is set to a non-UTC timezone (e.g., America/New_York), the date range you select may be incorrectly shifted. For example, an EST user selecting "2026-03-15 to 2026-03-20" would receive logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC" instead of the full calendar days in local time. This is a known bug ([$[DPLAT-DEF-05]$]) currently in progress. The workaround is to manually adjust the date range by adding/subtracting your timezone offset hours, or perform the export while logged in with a UTC timezone account.

### How to Filter Ad-hoc Reports

You can filter audit log exports using the **Audit Log Query Language (DSL)** documented in the Compliance Vault. The query language supports filtering by:

- **Event type**: `event_type=data_export`
- **Timestamp range**: `timestamp:[NOW-30d TO NOW]` (supports both absolute ISO-8601 and relative syntax like `-7d`, `-30d`)
- **Actor identity**: `actor_id=user@example.com` or `actor_role=admin`
- **Resource path**: `resource_path=/path/to/resource`
- **Custom metadata**: `metadata.source=connector-crm-001`

You can combine filters using logical operators (`AND`, `OR`, `NOT`) and apply aggregations like `AGGREGATE: count BY actor_role` (per [$[Audit Log — Query Language Reference]$]).

### Limits on Manual Exports

The following limits apply to manual exports:

- **Maximum events per query**: 100,000 events (per [$[Audit Log — Query Language Reference]$])
- **Export completion time**: Must complete within 30 seconds for datasets up to 100,000 log entries (per [$[DPLAT-REQ-10]$])
- **Concurrent exports**: Supports up to 5 compliance officers running exports simultaneously without degradation (per [$[DPLAT-REQ-10]$])
- **Export file encryption**: Files are encrypted at rest using AES-256 and in transit using TLS 1.3 (per [$[DPLAT-REQ-10]$])
- **Download link expiration**: Secure download link expires after 24 hours (per [$[DPLAT-010]$])
- **RBAC restriction**: Only users with the **Compliance Officer** role can trigger exports (per [$[DPLAT-REQ-10]$])

### Export Authorization Summary

The export functionality is strictly controlled through **Role-Based Access Control (RBAC)** — only users assigned the **Compliance Officer** role can trigger ad-hoc exports ([$[DPLAT-REQ-10]$]). All authorization decisions are logged to the immutable audit trail for compliance purposes. The exported files are encrypted both at rest (AES-256) and in transit (TLS 1.3), ensuring data security throughout the export lifecycle.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)

## Audit Trail

To perform a manual (ad-hoc) export of audit logs for compliance purposes, a **Compliance Officer** navigates to the **Compliance Vault → Audit Logs** section. There, they see a form with **start date**, **end date**, and **export format** options. After selecting the desired date range and format, they submit the request. The system generates the file and sends a **notification email** with a secure download link that expires after **24 hours** ([DPLAT-010]).

### Available Export Formats

The export supports three formats, selectable via a dropdown (CSV is the default):

- **CSV** – with proper headers, UTF-8 encoding, and escaped special characters
- **Parquet** – valid Apache Parquet with schema metadata and typed columns (~60% compression ratio)
- **JSON-NDJSON** – each line is a single valid JSON object representing one audit log entry ([DPLAT-040])

### Filtering Ad-hoc Reports

Compliance officers can filter audit log exports using the **domain-specific query language (DSL)** described in the [$[Audit Log — Query Language Reference]$]. Filters include:

- **Time-range filters**: absolute ISO-8601 ranges (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative shortcuts (`-7d`, `-30d`, `-90d`, `-1y`)
- **Event type**: e.g., `event_type=data_export`
- **Actor/role**: e.g., `actor_role=admin`
- **Resource path, IP address, connector ID, tenant ID**, and nested metadata fields
- **Logical operators**: `AND`, `OR`, `NOT` to combine filters

For example, to get all export activity in the last 30 days:
```
event_type=data_export AND timestamp:[NOW-30d TO NOW]
```

### Limits on Manual Exports

Based on the available sources, the following limits apply:

| Limit | Value | Source |
|-------|-------|--------|
| **Maximum events per query** | 100,000 events | [$[Audit Log — Query Language Reference]$] |
| **Export completion time** | Within 30 seconds for datasets up to 100,000 entries | [DPLAT-REQ-10] |
| **Concurrent exports** | Up to 5 compliance officers without degradation | [DPLAT-REQ-10] |
| **Secure download link expiry** | 24 hours | [DPLAT-010] |
| **Encryption** | AES-256 at rest, TLS 1.3 in transit | [DPLAT-REQ-10] |
| **Regex pattern length** | Limited to 100-byte patterns | [$[Audit Log — Query Language Reference]$] |
| **Aggregation groups** | Capped at 1,000 distinct groups | [$[Audit Log — Query Language Reference]$] |

### Important: Timezone Handling

There is a **known bug** ([DPLAT-DEF-05]) affecting non-UTC users: when a Compliance Officer with a timezone like America/New_York selects a date range, the exported records are shifted by the user's timezone offset. For example, an EST user selecting "2026-03-15 to 2026-03-20" receives logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC" instead of the full calendar days. The workaround is to manually adjust the date range or perform the export while logged in with a UTC timezone account. This bug is currently **In Progress** and not yet fixed.

### Audit Trail Aspect

The exported audit log includes all fields required for compliance: **timestamp, user, action, data source, and affected PII fields** ([DPLAT-010]). The export itself is logged in the immutable audit trail, ensuring that every export operation is itself auditable. Only users with the **Compliance Officer** role can trigger exports ([DPLAT-REQ-10]).

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)

## Security

### How to Perform a Manual Export (Security-Focused)

To trigger a manual (ad-hoc) export of audit logs, a **Compliance Officer** navigates to the Audit Log Export page in the Compliance Vault UI. According to [$[DPLAT-010]$], the officer selects a date range (start and end dates) and an export format (CSV, Parquet, or JSON-NDJSON, per [$[DPLAT-040]$]). The system then generates the export file and sends a notification email with a **secure download link that expires after 24 hours** (per [$[DPLAT-010]$] AC#3). Exported files are **encrypted at rest using AES-256** and **in transit using TLS 1.3**, as required by [$[DPLAT-REQ-10]$].

### How to Filter Ad-hoc Reports (Security Implications)

Filters are applied using the Compliance Vault's domain-specific query language (DSL), documented in [$[Audit Log — Query Language Reference]$]. Security-relevant filtering includes:
- **Event type**: e.g., `event_type=data_export` to isolate export activities
- **Actor role**: e.g., `actor_role=admin` to focus on privileged users
- **PII sensitivity**: e.g., `metadata.pii_sensitive=true` to filter events involving personally identifiable information
- **Time range**: Absolute ISO-8601 ranges or relative shortcuts like `-30d`

**Critical security note**: All authorization decisions for export requests are logged to the immutable audit trail (per [$[DPLAT-REQ-10]$]), ensuring every filtered query is traceable.

### Limits on Manual Exports (Security Constraints)

Several security-relevant limits apply:

| Limit | Value | Source |
|-------|-------|--------|
| **Maximum events per query** | 100,000 events | [$[Audit Log — Query Language Reference]$] |
| **Concurrent export requests** | Up to 5 compliance officers without degradation | [$[DPLAT-REQ-10]$] |
| **Export completion time** | Within 30 seconds for datasets up to 100,000 entries | [$[DPLAT-REQ-10]$] |
| **Download link expiration** | 24 hours | [$[DPLAT-010]$] |
| **Export job queue** | Can deadlock if 4+ exports are queued simultaneously (bug [$[DPLAT-DEF-18]$] — currently **In Progress**) | [$[DPLAT-DEF-18]$] |
| **Timezone handling** | Known bug: non-UTC users may experience shifted date ranges (bug [$[DPLAT-DEF-05]$] — currently **In Progress**) | [$[DPLAT-DEF-05]$] |

### Key Security Architecture

The audit log storage backend is **Postgres** (per [$[ADR-007]$]), chosen specifically for its **native Row-Level Security (RLS)** for multi-tenant isolation and **ACID transaction integrity** to prevent audit event loss. The export feature respects tenant retention policies—queries older than the configured retention period return empty results. Additionally, PII-tagged data is subject to a **30-day default retention** (per [$[PII Auto-Tagging — Policy and Behavior]$]), after which it is automatically anonymized or deleted.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)

## Troubleshooting

### How to Perform a Manual Export

To trigger a manual (ad-hoc) export of audit logs, navigate to the **Compliance Vault → Audit Log Export** page. As a compliance officer, you will see a form with the following options:

- **Start date** and **End date** fields for specifying the date range
- **Export format selector** with three options: CSV (default), Parquet, and JSON-NDJSON ([$[DPLAT-040]$])

After submitting the request, the system generates the export file and sends a notification email with a **secure download link that expires after 24 hours** ([$[DPLAT-010]$]). The exported CSV includes columns for timestamp, user, action, data source, and affected PII fields, with proper CSV escaping for special characters.

**Important RBAC note:** Only users with the **Compliance Officer** role can trigger exports ([$[DPLAT-REQ-10]$]).

### How to Filter Ad-hoc Reports

The audit log supports a domain-specific query language (DSL) for filtering events before export ([$[Audit Log — Query Language Reference]$]). Key filtering capabilities include:

- **Date range filters**: Use absolute ISO-8601 timestamps (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative ranges (`-7d`, `-30d`, `-90d`, `-1y`)
- **Event type filters**: `event_type=data_export`, `event_type IN (login, logout, data_export)`
- **Actor filters**: `actor_id`, `actor_role`
- **Resource filters**: `resource_path`, `connector_id`
- **Logical operators**: Combine filters with `AND`, `OR`, and `NOT`
- **Aggregations**: Summarize results with `AGGREGATE: count BY actor_role`

### Limits on Manual Exports

The following limits apply to manual exports:

| Limit | Value |
|-------|-------|
| Maximum events per query | 100,000 events ([$[Audit Log — Query Language Reference]$]) |
| Export completion time | Must complete within 30 seconds for datasets up to 100,000 entries ([$[DPLAT-REQ-10]$]) |
| Concurrent export requests | Up to 5 compliance officers without degradation ([$[DPLAT-REQ-10]$]) |
| Secure download link validity | 24 hours ([$[DPLAT-010]$]) |
| Regex pattern length | Maximum 100 bytes |
| Aggregation groups | Capped at 1,000 distinct groups |

### Known Troubleshooting Issues

1. **Timezone offset bug ([$[DPLAT-DEF-05]$])**: When a user with a non-UTC timezone (e.g., America/New_York) performs an ad-hoc export, the date range is incorrectly shifted by the user's timezone offset. For example, an EST user selecting "2026-03-15 to 2026-03-20" receives logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC", missing the first 5 hours and including 5 extra hours. **Workaround**: Manually adjust the date range by adding/subtracting the timezone offset, or perform the export while logged in with a UTC timezone account.

2. **Export queue deadlock ([$[DPLAT-DEF-18]$])**: When 4 or more export jobs are queued simultaneously, the export job queue can enter a deadlock state. Jobs remain in "Processing" status indefinitely, blocking all subsequent requests. **Workaround**: Manually cancel all queued exports via the admin console, restart the export service, and re-submit exports one at a time with 30-second intervals between submissions.

3. **Export job status monitoring**: You can check export job status in the **Connector Health Monitor** dashboard, which displays a panel showing the most recent export job status (Success, In Progress, Failed, or Not Run) with color-coded indicators ([$[DPLAT-043]$]).

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)

## Job Failures

### How to Perform a Manual Export

To perform a manual (ad-hoc) export of audit logs, a compliance officer navigates to the **Compliance Vault → Audit Log Export** page. There, they see a form with start date, end date, and export format options (CSV, Parquet, or JSON-NDJSON, with CSV as default) [$[DPLAT-010]$] [$[DPLAT-040]$]. After selecting the date range and format, the officer submits the request. The system then generates the export file and sends a notification email with a secure download link that expires after 24 hours [$[DPLAT-010]$].

**Important note on timezone handling:** There is a known bug [$[DPLAT-DEF-05]$] where users with non-UTC timezones (e.g., America/New_York) experience shifted date ranges. For example, an EST user selecting "2026-03-15 to 2026-03-20" receives logs from "2026-03-15 05:00:00 UTC to 2026-03-20 05:00:00 UTC", missing the first 5 hours and including 5 extra hours. The workaround is to manually adjust the date range or use a UTC timezone account. This bug is currently **In Progress**.

### How to Filter Ad-hoc Reports

Ad-hoc exports can be filtered using the Compliance Vault's domain-specific query language (DSL) [$[Audit Log — Query Language Reference]$]. Filters combine field names, operators, and values. Key filtering capabilities include:

- **By event type:** `event_type=data_export`
- **By status:** `status!=failed`
- **By date range:** `timestamp:[NOW-30d TO NOW]` (relative) or `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]` (absolute)
- **By actor role:** `actor_role=admin`
- **By data volume:** `bytes_transferred>100000000`
- **By PII fields:** `metadata.pii_fields IN (email, ssn, phone)`
- **By connector:** `connector_id=connector-crm-001`

Filters can be combined with logical operators (`AND`, `OR`, `NOT`). For example: `event_type=data_export AND actor_role=admin AND bytes_transferred>5000000`.

### Limits on Manual Exports

The following limits apply to manual exports:

| Limit | Value | Source |
|-------|-------|--------|
| Maximum events per query | 100,000 | [$[Audit Log — Query Language Reference]$] |
| Export completion time | Within 30 seconds for datasets up to 100,000 entries | [$[DPLAT-REQ-10]$] |
| Concurrent export requests | Up to 5 compliance officers without degradation | [$[DPLAT-REQ-10]$] |
| Export file encryption | AES-256 at rest, TLS 1.3 in transit | [$[DPLAT-REQ-10]$] |
| Download link expiration | 24 hours | [$[DPLAT-010]$] |
| Regex pattern length | Limited to 100-byte patterns | [$[Audit Log — Query Language Reference]$] |
| Aggregation groups | Capped at 1,000 distinct groups | [$[Audit Log — Query Language Reference]$] |

**Critical job failure issue:** There is a known deadlock bug [$[DPLAT-DEF-18]$] where the export job queue enters a deadlock state when **4 or more** export jobs are queued simultaneously. Jobs remain in "Processing" status indefinitely, consuming database connections and blocking all subsequent export requests. The workaround is to manually cancel all queued exports, restart the export service, and re-submit exports one at a time with 30-second intervals. This bug is currently **In Progress** with **High** priority.

**Export job status monitoring:** Workspace admins can monitor export job status (Success, In Progress, Failed, or Not Run) via the **Health Monitor** dashboard, which includes an "Audit Log Export" panel that refreshes automatically every 30 seconds [$[DPLAT-043]$]. Failed exports for scheduled jobs are retried up to 3 times with exponential backoff, with notification emails sent on permanent failure [$[DPLAT-009]$].

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)

## Timeout Handling

Based on the available documentation, here is what you need to know about performing manual exports, filtering ad-hoc reports, and the limits on manual exports, specifically focused on the **Timeout Handling** aspect.

### How to Perform a Manual Export

According to [$[DPLAT-010]$], a compliance officer can trigger an ad-hoc export by navigating to the Audit Log Export page, where they will see a form with start date, end date, and export format options. After submitting a date range export request, the system generates a CSV file containing all audit log entries within the specified range, including timestamp, user, action, data source, and affected PII fields. Upon completion, the officer receives a notification email with a secure download link that expires after 24 hours.

The export can be performed in three formats: CSV, Parquet, or JSON-NDJSON, as documented in [$[DPLAT-040]$].

### How to Filter Ad-hoc Reports

Per the [$[Audit Log — Query Language Reference]$], ad-hoc reports can be filtered using a domain-specific query language (DSL) that supports:
- **Comparison operators**: `=`, `!=`, `>`, `<`, `>=`, `<=`, `~` (regex), `IN` (set membership)
- **Logical operators**: `AND`, `OR`, `NOT`
- **Time-range syntax**: Both absolute ISO-8601 ranges (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) and relative ranges (`-7d`, `-30d`, `-90d`, `-1y`)
- **Field selectors**: Filter by `event_type`, `actor_id`, `actor_role`, `resource_path`, `ip_address`, `http_status`, `bytes_transferred`, `connector_id`, `tenant_id`, and `session_id`
- **Aggregations**: `COUNT`, `SUM`, `DISTINCT` with grouping

### Limits on Manual Exports

The following limits apply to manual exports:

1. **Maximum 100,000 events per query** (per the Query Language Reference)
2. **Regex matches limited to 100-byte patterns**
3. **Aggregations capped at 1,000 distinct groups**
4. **Export operation must complete within 30 seconds** for datasets up to 100,000 log entries (per [$[DPLAT-REQ-10]$])
5. **Concurrent exports**: Support for up to 5 compliance officers without degradation (per [$[DPLAT-REQ-10]$]), but note that [$[DPLAT-DEF-18]$] documents a known deadlock issue when 4+ exports are queued simultaneously

### Timeout Handling Specifics

The most critical timeout-related constraint is documented in [$[DPLAT-REQ-10]$]: **the export operation must complete within 30 seconds for datasets up to 100,000 log entries**. This is a measurable latency constraint that directly addresses timeout behavior.

However, there are several important timeout-related considerations:

1. **The 30-second timeout applies only to datasets up to 100,000 entries**. For larger datasets, the system behavior regarding timeouts is not explicitly documented in the provided sources.

2. **The export job queue can deadlock** if 4 or more exports are queued simultaneously, as reported in [$[DPLAT-DEF-18]$]. When this occurs, jobs remain in "Processing" status indefinitely, consuming database connections and blocking all subsequent export requests. The workaround is to manually cancel all queued exports, restart the export service, and re-submit exports one at a time with 30-second intervals between submissions.

3. **The secure download link expires after 24 hours** (per [$[DPLAT-010]$]), which is a timeout on the download window rather than the export generation itself.

4. **Failed exports are retried up to 3 times with exponential backoff** for scheduled exports (per [$[DPLAT-009]$]), though this behavior is documented for scheduled exports rather than ad-hoc ones.

5. **There is no documented timeout for the export generation process itself** beyond the 30-second latency constraint. The system does not appear to have a hard timeout that would cancel a long-running export; instead, the deadlock issue in [$[DPLAT-DEF-18]$] suggests that stalled jobs remain in "Processing" status indefinitely.

**Important caveat**: The known timezone offset bug documented in [$[DPLAT-DEF-05]$] can cause exported records to be shifted by the user's timezone offset, potentially affecting the accuracy of date-range filtering. This is not a timeout issue but could lead to compliance concerns if auditors rely on the exported data.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)

## Large Dataset Management

### How to Perform a Manual Export

To perform a manual ad-hoc export of audit logs, a compliance officer navigates to the **Audit Log Export** page in the Compliance Vault, where they see a form with **start date**, **end date**, and **export format** options (per [$[DPLAT-010]$]). After selecting a date range and format (CSV, Parquet, or JSON-NDJSON — see [$[DPLAT-040]$]), the system generates the export file. Upon completion, the user receives a notification email with a **secure download link that expires after 24 hours** (per [$[DPLAT-010]$]).

### Filtering Ad-hoc Reports

Filters can be applied using the **Audit Log Query Language (DSL)**, which supports filtering by event type, timestamp range, actor identity, resource path, and custom metadata (per [$[Audit Log — Query Language Reference]$]). For large dataset management, you can combine filters with logical operators (`AND`, `OR`, `NOT`) and use time-range syntax (absolute ISO-8601 or relative shortcuts like `-30d`). Example: `event_type=data_export AND timestamp:[NOW-30d TO NOW]`. Additionally, the export UI supports filtering by **user, data source, connector, and event type** (per [$[DPLAT-EPIC-05]$]).

### Limits on Manual Exports

For **large dataset management**, the following limits and constraints apply:

- **Query limit**: Maximum **100,000 events per query** (per [$[Audit Log — Query Language Reference]$])
- **Export generation latency**: Under **5 seconds for datasets up to 10,000 records** (per [$[DPLAT-EPIC-05]$])
- **Export job queue**: A known deadlock occurs when **4 or more exports are queued simultaneously** — the workaround is to submit exports one at a time with 30-second intervals (per [$[DPLAT-DEF-18]$])
- **Timezone issue**: Non-UTC users may experience date range shifts; the system currently applies the user's timezone offset incorrectly, so manual adjustment or using a UTC account is recommended (per [$[DPLAT-DEF-05]$])
- **Retry mechanism**: Failed exports are retried up to **3 times with exponential backoff** (per [$[DPLAT-009]$])

For managing truly large datasets (millions of records), the **SAP S/4HANA connector** demonstrates best practices: it uses **server-side paging** with configurable page size (500–10,000 records per page), **stream processing** to avoid memory exhaustion (memory usage below 500MB regardless of total record count), and **progress checkpoints** every 10,000 records for job resumption (per [$[DPLAT-012]$]). While this connector is for SAP data extraction, the same principles apply to audit log exports — consider breaking large exports into smaller date-range chunks to stay within the 100,000-event query limit.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-017] Salesforce — bulk migration tool from legacy v1 connector](https://demo-jira.local/browse/DPLAT-017)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)

## Logs

### How to Perform a Manual Export

To manually export audit logs, a compliance officer navigates to the Compliance Vault → Audit Log Export page. According to [JIRA] [$[DPLAT-010]$], the export form requires selecting a **start date** and **end date** to define the date range. After submitting the request, the system generates a CSV file containing all audit log entries within that range, including timestamp, user, action, data source, and affected PII fields. The export is delivered via a notification email with a secure download link that expires after 24 hours.

Per [JIRA] [$[DPLAT-040]$], you can also select the export format from a dropdown with three options: **CSV** (default), **Parquet**, or **JSON-NDJSON**. The export endpoint is `/api/v1/compliance/audit-query` (per [CONFLUENCE] [$[Audit Log — Query Language Reference]$]).

**Important timezone note**: Per [JIRA] [$[DPLAT-DEF-05]$], there is a known bug where non-UTC users experience a timezone offset shift in exported records. For example, an EST (UTC-5) user selecting "2026-03-15 to 2026-03-20" receives logs shifted by -5 hours. The workaround is to manually adjust the date range or use a UTC timezone account.

### How to Filter Ad-hoc Reports

The [CONFLUENCE] [$[Audit Log — Query Language Reference]$] documents a domain-specific query language (DSL) for filtering audit log events. Filters are submitted via the UI or the `/api/v1/compliance/audit-query` endpoint. Key filtering capabilities include:

- **Comparison operators**: `=` (exact match), `!=` (not equal), `>` / `<` (numeric), `~` (regex), `IN` (set membership)
- **Logical operators**: Combine filters with `AND`, `OR`, and `NOT`
- **Time-range syntax**: Absolute ISO-8601 ranges (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative shortcuts (`-7d`, `-30d`, `-90d`, `-1y`)
- **Available fields**: `event_type`, `actor_id`, `actor_role`, `resource_path`, `ip_address`, `http_status`, `bytes_transferred`, `connector_id`, `tenant_id`, `session_id`
- **Nested field access**: Dot notation for metadata (e.g., `metadata.source=connector-crm-001`)

Example filter for export activity in the last month:
```
event_type=data_export AND timestamp:[NOW-30d TO NOW]
```

### Limits on Manual Exports

Based on the provided sources, the following limits apply:

| Limit | Source | Value |
|-------|--------|-------|
| Maximum events per query | [CONFLUENCE] [$[Audit Log — Query Language Reference]$] | 100,000 events |
| Regex pattern length | [CONFLUENCE] | 100 bytes max |
| Aggregation groups | [CONFLUENCE] | 1,000 distinct groups max |
| Compressed CSV size (90 days) | [JIRA] [$[DPLAT-REQ-08]$] | ≤ 4 GB per tenant |
| Export generation latency (90 days) | [JIRA] [$[DPLAT-REQ-08]$] | ≤ 5 minutes for ≤100K daily events |
| Download link expiration | [JIRA] [$[DPLAT-010]$] | 24 hours |
| Concurrent export jobs | [JIRA] [$[DPLAT-DEF-18]$] | **Deadlock risk at 4+ queued exports** (known bug) |
| Export success rate | [JIRA] [$[DPLAT-REQ-08]$] | 99.9% target |
| Audit retention | [GITHUB] audit-log-service README | 2,555 days (default) |

**Key limitation to note**: Per [JIRA] [$[DPLAT-DEF-18]$], queuing 4 or more export jobs simultaneously can cause a deadlock where all jobs stall in "Processing" status. The workaround is to submit exports one at a time with 30-second intervals.

**Sources:**
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-DEF-18] Audit Log — export job queue can deadlock if 4+ exports queued](https://demo-jira.local/browse/DPLAT-DEF-18)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-027] Health Monitor — Datadog metrics exporter integration](https://demo-jira.local/browse/DPLAT-027)
