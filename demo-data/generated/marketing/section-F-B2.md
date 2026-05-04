# F-B2  Audit Log Export — One-Pager

_Feature: `F-B2` · Audience: external-prospect, marketing-manager_

> 2-page brief for compliance officers seeking audit-log automation

## Hero & Value Proposition

### What Does the Audit Log Export Do?

The Audit Log Export feature, part of the Amisol DataPlatform's Compliance Vault module, enables compliance officers to securely retrieve and share verifiable, tamper-proof records of all data access and modification events across tenant workspaces. It transforms raw audit data into exportable, cryptographically sealed archives that satisfy regulatory requirements for external audits, internal reviews, and forensic investigations.

At its core, the feature provides on-demand and scheduled export of audit logs with configurable date ranges, advanced filtering by user, data source, connector, and event type, and secure delivery via encrypted, time-limited download links. Exports can be generated in CSV, Parquet, or JSON-NDJSON formats, allowing seamless integration with downstream compliance and analytics tools.

### Integrity and Retention Properties

Every export is protected by **AES-256-GCM encryption** and includes a **signed manifest** containing a SHA-256 hash of the audit log data, export timestamp, and tenant identifier, digitally signed with RSA-2048. This cryptographic chain ensures **data integrity** and **non-repudiation** — auditors can verify that exported records have not been altered since creation. A built-in "Verify Export" tool allows compliance officers to validate the manifest signature and confirm archive integrity without decryption.

For retention, the system retains audit records for **2,555 days (7 years)** by default, stored in PostgreSQL with row-level security for multi-tenant isolation. Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with all access to export operations logged to the immutable audit trail. Scheduled exports to customer-managed S3 buckets support daily, weekly, or monthly cadences for off-platform backups.

### Supported Integrations and Export Formats

The feature supports three export formats:
- **CSV** — with proper headers, UTF-8 encoding, and escaped special characters
- **Parquet** — Apache Parquet with typed columns and row group compression (~60% compression ratio)
- **JSON-NDJSON** — one valid JSON object per line, no array wrappers

Integrations include:
- **ServiceNow** — direct export of audit findings as ITSM incidents with severity mapping based on PII sensitivity levels
- **S3-compatible storage** — scheduled exports to customer-managed buckets with IAM role authentication
- **Health Monitor dashboard** — export job status visible alongside connector health indicators
- **Full-text search** — Elasticsearch-based indexing across historical exports for rapid compliance investigations

All exports are restricted to the **Compliance Officer** role via RBAC, ensuring only authorized personnel can trigger or access audit log data.

**Sources:**
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)

## Regulatory Context

### What Does the Audit Log Export Do?

The Audit Log Export feature, part of the MOD-B Compliance Vault module, enables compliance officers to securely retrieve and share historical audit trails for regulatory reviews, external audits, and forensic analysis. It provides on-demand and scheduled export of all compliance-critical events—including data access, modifications, and administrative actions—across the Amisol DataPlatform. The feature is designed to meet regulatory requirements for producing verifiable, tamper-evident records of who accessed what data, when, and from which tenant context.

### Integrity and Retention Properties

**Integrity:** The export ensures cryptographic proof of authenticity and non-repudiation. Per [$[DPLAT-014]$], exports generate an AES-256-GCM encrypted .zip archive containing the audit log CSV and a separate manifest.json file. The manifest includes a SHA-256 hash of the CSV, export timestamp, tenant identifier, and an RSA-2048 digital signature verifiable via the platform's public key. A "Verify Export" button allows compliance officers to validate the manifest signature and confirm archive integrity without decryption. All exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with access logged to the immutable audit trail.

**Retention:** The system retains audit records for a configurable period, with a default of 2,555 days (approximately 7 years) per the audit-log-service configuration. The storage backend uses PostgreSQL, chosen for its ACID transaction integrity and row-level security for multi-tenant isolation. Retention policies can leverage existing pg_cron infrastructure for TTL-based management. A full 90-day export is designed to fit within 4 GB compressed CSV per tenant, with export generation completing within 5 minutes for tenants with up to 100K daily events.

### Integrations and Export Formats

**Export Formats:** Compliance officers can select from three formats via a dropdown UI: CSV (default), Apache Parquet, and JSON-NDJSON. CSV exports include proper headers and UTF-8 encoding. Parquet exports produce valid files with typed columns and row group compression (~60% compression ratio). JSON-NDJSON exports generate one valid JSON object per line per audit entry.

**Integrations:**
- **S3 Bucket Export:** Workspace admins can configure scheduled CSV exports (daily/weekly/monthly) to customer-managed S3 buckets for off-platform backups, with automatic retry (up to 3 times with exponential backoff) and notification on permanent failure.
- **ServiceNow Integration (planned for v2.5):** Per [$[DPLAT-015]$], a future capability will allow direct export to ServiceNow, automatically creating ITSM tickets with proper severity mapping based on PII sensitivity levels.
- **Health Monitor Dashboard:** Export job status (Success, In Progress, Failed, Not Run) is visible in the Connector Health Monitor dashboard, with color-coded indicators and auto-refresh every 30 seconds.
- **Full-Text Search (in progress for v2.4):** Elasticsearch-based indexing will enable compliance officers to search across historical exports by keywords, with results returning within 3 seconds for datasets up to 100,000 records.

**Access Control:** Only users with the Compliance Officer role can trigger exports, with all authorization decisions logged to the immutable audit trail. Exported files are delivered via secure download links that expire after 24 hours.

**Sources:**
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)

## Three Key Capabilities

The Audit Log Export feature (F-B2) within the MOD-B Compliance Vault enables compliance officers and workspace administrators to securely retrieve, package, and deliver historical audit trails for regulatory reviews, forensic analysis, and off-platform compliance retention. It provides three core capabilities:

### 1. On-Demand and Scheduled Export with Flexible Filtering

Compliance officers can trigger **ad-hoc exports** with customizable date ranges, retrieving all audit log entries within a specified period—including timestamp, user, action, data source, and affected PII fields. Exports complete within 5 seconds for datasets up to 10,000 records and within 30 seconds for up to 100,000 entries ([$[DPLAT-010]$], [$[DPLAT-EPIC-05]$]). For ongoing compliance needs, workspace administrators can configure **scheduled exports** (daily, weekly, or monthly) to customer-managed S3 buckets, with automatic retry (up to 3 attempts with exponential backoff) and email notifications on permanent failure ([$[DPLAT-009]$]). Advanced filtering by user, data source, connector, and event type supports targeted compliance reviews, and a full-text search capability across historical exports allows rapid location of specific events ([$[DPLAT-037]$]).

### 2. Integrity and Retention Properties

**Data Integrity**: Exported archives are encrypted using **AES-256-GCM** and include a signed manifest containing a SHA-256 cryptographic hash of the audit log CSV, export timestamp, tenant identifier, and an **RSA-2048 digital signature** verifiable via the platform's public key. A "Verify Export" button allows compliance officers to validate manifest signature and confirm archive integrity without decryption, ensuring non-repudiation ([$[DPLAT-014]$]).

**Retention**: The system retains audit records for **2,555 days (7 years)** by default, with configurable retention policies per tenant. Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with access-controlled download links that expire after 24 hours ([$[DPLAT-EPIC-05]$], [$[DPLAT-REQ-08]$]). All authorization decisions are logged to the immutable audit trail ([$[DPLAT-REQ-10]$]).

### 3. Integrations and Export Formats

**Export Formats**: Compliance officers can select from three formats via a dropdown UI:
- **CSV** (default) — with proper headers, escaped special characters, and UTF-8 encoding
- **Parquet** — valid Apache Parquet with schema metadata, typed columns, and ~60% compression ratio
- **JSON-NDJSON** — each line a single valid JSON object, no trailing commas or array wrappers

([$[DPLAT-040]$])

**Integrations**: The export supports direct delivery to **ServiceNow** for ITSM ticketing, where exported findings automatically create incidents with severity mapping based on PII sensitivity level. The connector allows configuration of instance URL, API token, and target ticket category, with retry capability for failed transmissions ([$[DPLAT-015]$]). Additionally, the **Connector Health Monitor** dashboard displays a dedicated "Audit Log Export" panel showing the most recent job status (Success, In Progress, Failed, or Not Run) with automatic 30-second refresh ([$[DPLAT-043]$]).

**Access Control**: Only users with the **Compliance Officer** role can trigger exports, with all authorization decisions logged to the immutable audit trail ([$[DPLAT-REQ-10]$]).

**Sources:**
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)

## Customer-Visible Benefits

### What Does the Audit Log Export Do?

The Audit Log Export feature enables compliance officers to securely retrieve and share immutable records of all data access, modifications, and administrative actions across the Amisol DataPlatform. It provides on-demand and scheduled export capabilities so organizations can produce verifiable audit trails for regulatory reviews, external audits, and internal compliance investigations. Compliance officers can trigger ad-hoc exports with customizable date ranges, user filters, and event type selections, or configure automated exports to customer-managed S3 buckets on daily, weekly, or monthly schedules. All exports are delivered via secure, time-limited download links that expire after 24 hours, ensuring sensitive data remains protected in transit.

### Integrity and Retention Properties

Every exported audit log archive is protected with **AES-256-GCM encryption** and includes a **signed manifest** containing a SHA-256 cryptographic hash of the exported data, the export timestamp, and a tenant identifier. The manifest is digitally signed using RSA-2048, providing cryptographic proof of authenticity and non-repudiation — meaning auditors can verify that the exported records have not been tampered with since export. A built-in "Verify Export" tool allows compliance officers to validate the manifest signature and confirm archive integrity without needing to decrypt the file.

For retention, the system stores audit records for a configurable period (default 2,555 days, approximately 7 years) using PostgreSQL with row-level security for tenant isolation. A full 90-day export compresses to under 4 GB per tenant, making it practical for quarterly reviews and long-term archival. Exports are encrypted at rest (AES-256) and in transit (TLS 1.3+), with all export operations themselves logged to the immutable audit trail for complete chain of custody.

### Supported Integrations and Export Formats

The feature supports **three export formats** to integrate with downstream compliance and analytics tools:

- **CSV** — Default format with proper headers, UTF-8 encoding, and correctly escaped special characters
- **Parquet** — Columnar format with schema metadata and ~60% compression ratio, ideal for big data analytics
- **JSON-NDJSON** — One valid JSON object per line, suitable for streaming ingestion into data pipelines

For integrations, the system supports:
- **Scheduled export to S3 buckets** — Automated delivery to customer-managed cloud storage with IAM role authentication and automatic retry (up to 3 attempts with exponential backoff)
- **ServiceNow integration** (planned for v2.5) — Direct export of audit findings as ITSM incidents with severity mapping based on PII sensitivity levels
- **Health Monitor dashboard** — Real-time visibility into export job status (Success, In Progress, Failed, or Not Run) alongside connector health indicators

Access to the export feature is restricted exclusively to the **Compliance Officer** role via role-based access control (RBAC), ensuring only authorized personnel can initiate or configure exports.

**Sources:**
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)

## Compliance & Security Highlights

### What It Does

The Audit Log Export feature, part of the MOD-B Compliance Vault module, enables compliance officers to securely retrieve and share immutable records of all data access and modification events across the Amisol DataPlatform. It provides on-demand and scheduled export of audit trails that capture who accessed what data, when, and from which tenant context — essential for regulatory reviews, external audits, and forensic analysis.

### Integrity & Retention Properties

**Data Integrity:** Every exported audit log archive is protected by cryptographic safeguards. The system generates an encrypted `.zip` archive containing the audit log CSV and a separate `manifest.json` file. The manifest includes a SHA-256 cryptographic hash of the CSV, the export timestamp, tenant identifier, and an RSA-2048 digital signature verifiable via the platform's public key. The entire archive is encrypted using AES-256-GCM, with the decryption password derived from a user-provided passphrase using PBKDF2 with at least 100,000 iterations. A "Verify Export" tool allows compliance officers to validate the manifest signature and confirm archive integrity without decryption — ensuring non-repudiation and tamper-proof evidence for auditors.

**Retention:** The system retains audit records for a configurable period, with a default of 2,555 days (approximately 7 years). Retention policies are managed per tenant, supporting both hot storage (12 months) and archived storage for longer-term compliance requirements. Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3+), with all access to exports logged to the immutable audit trail.

### Supported Integrations & Export Formats

**Export Formats:** Compliance officers can select from three export formats via a dropdown UI:
- **CSV** (default) — with proper headers, UTF-8 encoding, and correctly escaped special characters
- **Parquet** — producing valid Apache Parquet files with typed columns and row group compression (~60% compression ratio)
- **JSON-NDJSON** — where each line contains a single valid JSON object representing one audit log entry

**Integrations:**
- **S3 Bucket Export:** Workspace admins can configure scheduled CSV exports (daily/weekly/monthly) to customer-managed S3 buckets for off-platform backups, with automatic retry (up to 3 times with exponential backoff) and notification on permanent failure
- **ServiceNow Integration** *(planned for v2.5)*: Export audit logs directly to ServiceNow to automatically create ITSM incidents with proper severity mapping based on PII sensitivity levels
- **Health Monitor Dashboard:** Export job status (Success, In Progress, Failed, Not Run) is visible in the Connector Health Monitor dashboard, with auto-refresh every 30 seconds

**Access Control:** Only users with the Compliance Officer role can trigger exports, with all authorization decisions logged to the immutable audit trail. Secure download links expire after 24 hours.

**Performance:** Full 90-day exports for tenants with ≤100K daily events complete within 5 minutes, with compressed CSV size not exceeding 4 GB per tenant. Export generation for datasets up to 10,000 records completes in under 5 seconds.

**Sources:**
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)

## Get a Demo

### What Does the Audit Log Export Do?

The Audit Log Export feature, part of the Compliance Vault module in the Amisol DataPlatform, gives compliance officers the ability to retrieve and securely share historical records of all data access and modification events across your organization. Think of it as a tamper-proof, exportable journal that tracks **who accessed what PII data, when, and from which tenant context** — perfect for external audits, regulatory reviews, and forensic investigations.

During a demo, you'll see how a compliance officer can trigger an ad-hoc export with a simple date range filter, select from multiple export formats, and receive a secure download link that expires after 24 hours. The system generates the export in under 5 seconds for datasets up to 10,000 records, making it fast enough for live demonstrations.

### Integrity and Retention Properties

**Integrity:** Every export is cryptographically protected. The system generates an encrypted archive (AES-256-GCM) containing the audit log CSV and a signed manifest file. The manifest includes a SHA-256 hash of the CSV, an export timestamp, and an RSA-2048 digital signature — all verifiable via the platform's public key. A "Verify Export" button lets compliance officers confirm the archive's authenticity without decrypting it.

**Retention:** Audit logs are retained for **2,555 days (7 years)** by default, configurable per tenant. Exports themselves are encrypted at rest (AES-256) and delivered over TLS 1.3. Access to the export feature is strictly controlled via Role-Based Access Control (RBAC) — only users with the Compliance Officer role can trigger exports, and every authorization decision is logged to the immutable audit trail.

### Supported Integrations and Export Formats

**Export Formats (selectable via dropdown):**
- **CSV** (default) — with proper headers, UTF-8 encoding, and correctly escaped special characters
- **Parquet** — Apache Parquet format with typed columns and ~60% compression ratio
- **JSON-NDJSON** — one valid JSON object per line, no trailing commas or array wrappers

**Integrations:**
- **S3 Bucket Export** — configure scheduled (daily/weekly/monthly) CSV exports to your own S3 bucket for off-platform backups, with automatic retry (up to 3 attempts) and email notifications on failure
- **ServiceNow Integration** *(coming in v2.5)* — export audit findings directly as ServiceNow incidents with proper severity mapping based on PII sensitivity levels
- **Health Monitor Dashboard** — view export job status (Success/In Progress/Failed) alongside connector health indicators, refreshed every 30 seconds

**Known Issue (for your awareness):** A timezone offset bug exists in v2.3 where non-UTC users may experience shifted date ranges during ad-hoc exports. A fix is in progress for an upcoming release.

**Sources:**
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-05] Audit Log Export ad-hoc range fails with timezone offset for non-UTC users](https://demo-jira.local/browse/DPLAT-DEF-05)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
