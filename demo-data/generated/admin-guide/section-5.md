# 5  Compliance and reporting

> High-level compliance oversight and reporting.

## Compliance Framework

### How to Generate Compliance Reports

To generate compliance reports within the Compliance Framework, you use the **Audit Log Export** feature (F-B2) of the Compliance Vault (MOD-B). The primary method is through an **ad-hoc export** with a customizable date range, as implemented in [$[DPLAT-010]$] (per [JIRA]).

**Step-by-step process:**
1. Navigate to the **Audit Log Export** page in the Compliance Vault UI
2. Specify a **start date** and **end date** for the desired reporting period
3. Select an **export format** (JSON, CSV, or PDF — per [CONFLUENCE] Compliance Vault — Module Overview)
4. Submit the request

The system generates the file and sends a **notification email** with a **secure download link** that expires after 24 hours (per [JIRA] DPLAT-010). For CSV exports, the file includes a header row with column names and proper CSV escaping.

### Reporting Capabilities

The Compliance Framework offers several reporting capabilities:

**1. Advanced Query DSL** — The audit log exposes a domain-specific query language (DSL) via the `/api/v1/compliance/audit-query` endpoint (per [CONFLUENCE] Audit Log — Query Language Reference). This supports:
- Filtering by event type, timestamp range, actor identity, resource path, and custom metadata
- Logical operators (`AND`, `OR`, `NOT`) for complex queries
- Aggregations: `COUNT`, `SUM(bytes_transferred)`, `DISTINCT(actor_id)` grouped by fields like `actor_role` or `event_type`
- Both absolute ISO-8601 time ranges and relative shortcuts (`-7d`, `-30d`, `-90d`, `-1y`)

**2. Export Formats** — Compliance officers can export audit logs in three formats (per [CONFLUENCE] Compliance Vault — Module Overview):
- **JSON** — Machine-readable for automated processing
- **CSV** — Spreadsheets for manual review
- **PDF** — Human-readable reports with digital signatures for legal proceedings

**3. Batch Sign-Off** — A planned feature ([$[DPLAT-039]$], per [JIRA]) will allow compliance officers to batch review and sign off up to 50 tenant audit log exports, generating a single batch sign-off certificate (PDF) with officer name, timestamp, and unique certificate ID.

**4. ServiceNow Integration** — A planned feature ([$[DPLAT-015]$], per [JIRA]) will enable direct export to ServiceNow for automatic ITSM ticket creation based on audit findings.

### How Compliance is Monitored

Compliance monitoring operates through several mechanisms:

**1. Immutable Audit Trail** — All data access, modification, permission changes, configuration changes, and authentication events are captured in an append-only `audit_events` table in PostgreSQL (per [CONFLUENCE] Audit Log v1 Architecture). The system uses **SHA-256 hash chaining** to link audit entries, preventing retroactive tampering (per [JIRA] DPLAT-042).

**2. PII Auto-Tagging (F-B1)** — At ingestion time, the PII detection engine automatically scans data using a hybrid rule+ML approach, tagging identified PII with metadata (type, confidence score, position). Each classification event creates an audit log entry (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior).

**3. PII Override Tracking** — When workspace admins override automatic PII classifications, the system automatically captures the decision in the audit log within 500ms, including user ID, timestamp, original classification, new classification, and data record identifier (per [JIRA] DPLAT-042).

**4. Retention Policy Enforcement** — The Compliance Vault retains audit logs according to the tenant's configured retention policy (default: 2555 days, or ~7 years, per [GITHUB] compliance-vault and audit-log-service). PII-tagged data has a platform-wide default retention of **30 days** before automatic anonymization or deletion (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior).

**5. Access Control** — Only authorized roles can access audit data: workspace admins (own tenant), compliance officers (all tenants), and support (with approval). All audit data is encrypted at rest (AES-256) and in transit (TLS 1.3) (per [CONFLUENCE] Audit Log v1 Architecture).

**6. Data Residency Controls** — PII-tagged data is subject to strict residency rules under GDPR Art. 44 and BDSG, with region-aware routing ensuring data never leaves its designated region without appropriate safeguards (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior).

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)

## Regulatory Mapping

### How to Generate Compliance Reports

To generate compliance reports focused on regulatory mapping, you use the **Audit Log Export** feature (F-B2) of the Compliance Vault (MOD-B). The process involves:

1. **Accessing the Export Functionality**: Only users with the **Compliance Officer** role can trigger exports, as enforced by RBAC (per [$[DPLAT-REQ-10]$]). Navigate to the Compliance Vault UI or use the API endpoint `/api/v1/compliance/audit-query`.

2. **Filtering by Regulatory Criteria**: Use the domain-specific query language (DSL) to filter events relevant to regulatory mapping. For example, to map PII access patterns for GDPR/BDSG compliance, you can query:
   - `event_type=data_export AND timestamp:[NOW-30d TO NOW]` — to see all data export activity in the last 30 days.
   - `metadata.pii_sensitive=true AND connector_id=connector-crm-001` — to isolate PII access from a specific data source like Salesforce or SAP S/4.
   - `actor_role=admin AGGREGATE: count BY event_type` — to summarize admin actions for accountability.

3. **Selecting Export Format**: Choose from **CSV**, **Parquet**, or **JSON-NDJSON** (per [$[DPLAT-040]$]). CSV is default for manual review; JSON-NDJSON is ideal for SIEM integration; Parquet offers efficient compression (~60% ratio) for large datasets.

4. **Executing the Export**: Use the CLI tool or UI. Example command:
   ```bash
   dplat audit-export \
     --start "2026-01-01" \
     --end "2026-03-31" \
     --event-type "pii_access,pii_export,pii_delete" \
     --tenant "acme-corp" \
     --format jsonl \
     --output s3://compliance-bucket/audit-q1-2026/
   ```
   Exports complete within 30 seconds for up to 100,000 events (per [$[DPLAT-REQ-10]$]).

### Reporting Capabilities

The Compliance Vault provides the following capabilities for regulatory mapping:

- **Immutable Audit Trail**: All data access, modification, permission changes, and PII override decisions are logged in the `audit_events` table with SHA-256 hash chaining to prevent tampering (per [$[DPLAT-042]$]).
- **Granular Filtering**: Filter by event type, actor, resource path, IP address, and nested metadata (e.g., `metadata.pii_fields IN (email, ssn)`).
- **Aggregations**: Summarize data by role, event type, or data volume (e.g., `SUM(bytes_transferred) BY event_type`).
- **Export Integrity**: Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3), with access-controlled download links expiring after 24 hours (per [$[DPLAT-EPIC-05]$]).
- **PII Context**: Reports include PII categories (email, phone, national ID, etc.) detected by the **Hybrid PII Classifier** (F-B1), with confidence scores and model version recorded in the audit log (per [$[DPLAT-REQ-17]$]).

### How Compliance is Monitored

Compliance monitoring for regulatory mapping is achieved through:

- **Automated PII Detection**: The PII Auto-Tagging engine (F-B1) scans all ingested data from connectors (Salesforce, SAP S/4, flat files) using ML classifiers and regex patterns. Every tagging decision is logged with model version, confidence score, and PII category (per [$[DPLAT-REQ-17]$]).
- **Override Tracking**: When workspace admins manually override a PII classification, the system automatically captures the user ID, timestamp, original/new classification, and data record identifier in the audit log with hash chaining (per [$[DPLAT-042]$]).
- **Retention Policy Enforcement**: Audit logs are retained per tenant policy (default 7 years for compliance tenants). Exported logs maintain the same retention period. Note: a known issue ([$[DPLAT-DEF-04]$]) may cause up to 48-hour retention overage for custom policies configured before v2.0.
- **Role-Based Access**: Only Compliance Officers can trigger exports; Workspace Admins can view logs for their own tenant; Data Stewards can review PII classifications (per [$[Compliance Vault — Module Overview]$]).
- **Performance Guarantees**: PII detection latency ≤ 500ms per record, false-negative rate ≤ 2% on regulatory test sets, and export availability 99.9% during business hours (per [$[DPLAT-REQ-17]$] and [$[DPLAT-REQ-10]$]).

### Key Regulatory Mapping Workflow

For a compliance officer mapping regulatory requirements (e.g., GDPR Article 30 records of processing activities, BDSG §46 documentation):

1. **Identify PII across data sources**: Enable PII Auto-Tagging for all workspaces (Settings → Compliance Vault).
2. **Review PII access patterns**: Query audit logs for `metadata.pii_sensitive=true` grouped by connector and actor.
3. **Export evidence**: Generate a CSV or PDF report filtered by date range and event type, including PII override decisions.
4. **Validate retention**: Confirm exported logs cover the required retention period (e.g., 7 years for GDPR).
5. **Submit for audit**: Use the digitally signed PDF format for legal proceedings (per [$[Compliance Vault — Module Overview]$]).

**Sources:**
- 📋 [[DPLAT-REQ-17] PII — false-negative rate target ≤ 0.02 on regulatory test set](https://demo-jira.local/browse/DPLAT-REQ-17)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Release Notes — v2.3 (April 2026)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/fc4e516f49c5)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)

## Policy Alignment

`⚠ stale`

To generate compliance reports focused on **Policy Alignment**, you use the **Compliance Vault** module's audit log query and export capabilities. The system is designed to demonstrate that data handling policies—particularly PII auto-tagging, retention, and access control—are being consistently applied across all data sources.

### How to Generate Compliance Reports

1. **Query the Audit Log**: Submit queries via the `/api/v1/compliance/audit-query` endpoint or the Compliance Vault UI using the domain-specific query language (DSL). For policy alignment, you would filter by event types that indicate policy enforcement, such as `data.access`, `data.modify`, or `config.change` (per [$[Audit Log v1 Architecture (Legacy)]$]).

2. **Filter by PII Override Decisions**: Since policy alignment includes verifying that manual overrides to auto-tagging are properly tracked, you can filter by `event_type=override` to see all PII classification overrides. Per [$[DPLAT-042]$], each override is automatically captured in the audit log with an immutable SHA-256 hash chain, including the user ID, timestamp, original classification, new classification, and data record identifier.

3. **Use Time-Range Filters**: Apply relative or absolute time ranges (e.g., `timestamp:[NOW-30d TO NOW]`) to focus on a specific compliance period. The system supports ISO-8601 absolute ranges and relative shortcuts like `-30d` (last 30 days) (per [$[Audit Log — Query Language Reference]$]).

4. **Export Reports**: Once your query returns results, export the data in your preferred format—CSV, Parquet, or JSON-NDJSON—via the export UI. Only users with the **Compliance Officer** role can trigger exports (per [$[DPLAT-REQ-10]$]). Exports are encrypted at rest with AES-256 and in transit with TLS 1.3, and download links expire after 24 hours.

### Reporting Capabilities

- **Advanced Filtering**: Filter by event type, actor role, resource path, tenant, connector, and custom metadata fields (e.g., `metadata.pii_sensitive=true`).
- **Aggregations**: Summarize results using `AGGREGATE: count BY event_type` or `SUM(bytes_transferred) BY event_type` to show policy compliance patterns.
- **Format Flexibility**: Choose between CSV (default), Parquet (with ~60% compression), or JSON-NDJSON for downstream compliance tools.
- **Export Metadata**: Each export is tracked with requestor identity, timestamp, record count, and retention status.

### How Compliance Is Monitored

Compliance monitoring for **Policy Alignment** is built into the ingestion pipeline:

- **At-Ingestion Classification**: PII is detected and tagged synchronously during data ingestion using a hybrid rule+ML model (confidence threshold ≥0.75). This ensures policy is applied before data enters analytics pipelines (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Immutable Audit Trail**: Every classification event, override, and access action is recorded in the `audit_events` table (PostgreSQL or ClickHouse backend) with a retention period of **2,555 days** (7 years) by default (per [$[compliance-vault]$] and [$[audit-log-service]$]).
- **Retention Policy Enforcement**: PII-tagged data is automatically anonymized or deleted after **30 days** (platform default), with per-tenant overrides available through a compliance review process (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Data Residency Controls**: PII data is routed to the correct regional storage based on detected origin (EU, DE, US), ensuring alignment with GDPR Art. 44 and BDSG requirements.

In summary, to generate a policy alignment report, you query the audit log for events related to PII classification, overrides, and data access, then export the filtered results. The system automatically monitors compliance through real-time tagging, immutable logging, and retention enforcement.

**Sources:**
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)

## Governance

`⚠ stale`

### How to Generate Compliance Reports

To generate compliance reports, a **Compliance Officer** uses the **Audit Log Export** feature (F-B2) within the Compliance Vault module. The process is as follows:

1. **Navigate** to the Compliance Vault interface and select the Audit Log Export page.
2. **Configure the export** by specifying:
   - A **date range** (absolute ISO-8601 timestamps or relative shortcuts like `-30d` for the last 30 days) — per [$[Audit Log — Query Language Reference]$]
   - Optional **filters** using the domain-specific query language (DSL), e.g., `event_type=data_export AND actor_role=admin` — per [$[Audit Log — Query Language Reference]$]
   - An **export format**: CSV (default), Parquet, or JSON-NDJSON — per [$[DPLAT-040]$]
3. **Submit the request**. The system generates the export within **30 seconds for datasets up to 100,000 log entries** — per [$[DPLAT-REQ-10]$]
4. **Receive a secure download link** via email, which **expires after 24 hours** — per [$[DPLAT-010]$]
5. **Download the file**. Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3) — per [$[DPLAT-REQ-10]$]

### Reporting Capabilities

The Compliance Vault provides the following reporting capabilities:

| Capability | Details |
|------------|---------|
| **Export Formats** | CSV, Parquet, JSON-NDJSON — per [$[DPLAT-040]$] |
| **Filtering** | By event type, timestamp range, actor identity, resource path, IP address, connector, tenant, and custom metadata — per [$[Audit Log — Query Language Reference]$] |
| **Aggregations** | Count, sum, distinct values grouped by fields like `actor_role` or `event_type` — per [$[Audit Log — Query Language Reference]$] |
| **Full-Text Search** | Across historical exports (in development for v2.4) — per [$[DPLAT-037]$] |
| **Batch Sign-Off** | Review and certify up to 50 exports at once, generating a PDF certificate (planned for v2.5) — per [$[DPLAT-039]$] |
| **PII Override Tracking** | All manual PII classification changes are automatically logged with hash chaining for tamper evidence — per [$[DPLAT-042]$] |

### How Compliance Is Monitored

Compliance monitoring is governed by **role-based access control (RBAC)** and an **immutable audit trail**:

- **Access Control**: Only the **Compliance Officer** role can trigger audit log exports. Workspace admins can read their own tenant's logs, but cannot export — per [$[DPLAT-REQ-10]$] and [$[Audit Log v1 Architecture (Legacy)]$]
- **Immutable Logging**: Every data access, modification, permission change, configuration change, and authentication event is recorded in the `audit_events` table with an append-only design — per [$[Audit Log v1 Architecture (Legacy)]$]
- **PII Monitoring**: The PII Auto-Tagging engine (F-B1) scans all ingested data and tags sensitive fields. All override decisions are automatically captured in the audit log with SHA-256 hash chaining — per [$[DPLAT-042]$] and [$[Compliance Vault — Module Overview]$]
- **Retention**: Audit logs are retained indefinitely (no automatic deletion) — per [$[Audit Log v1 Architecture (Legacy)]$]. The Compliance Vault service has a configurable retention period (default 2555 days / ~7 years) — per [$[compliance-vault README]$]
- **Regulatory Alignment**: The system is designed to meet GDPR and German BDSG requirements, including data subject rights, documentation obligations, and automated decision-making documentation — per [$[Compliance Vault — Module Overview]$]

### Governance Summary

The Compliance Vault provides a **self-service governance layer** where Compliance Officers can independently:
- Query and export audit logs with granular filtering
- Monitor PII access patterns and classification changes
- Certify compliance reports through batch sign-off workflows
- Rely on immutable, tamper-evident records for forensic analysis and regulatory audits

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)

## Standards

To generate compliance reports focused on **standards**, you use the **Compliance Vault's audit log export capabilities**, which are designed to help organizations meet regulatory standards such as GDPR and CCPA.

### How to Generate Compliance Reports (Standards-Focused)

1. **Access the Export Feature**: Compliance officers (the only role authorized per [JIRA] [DPLAT-REQ-10]) can initiate exports via the Compliance Vault UI or the command-line interface.

2. **Apply Standards-Relevant Filters**: Use the Audit Log Query DSL to filter events by criteria that map to regulatory standards. For example:
   - **PII Access Events** (relevant to GDPR/CCPA data subject access rights): Filter by `event_type=pii_access` or `metadata.pii_sensitive=true`
   - **Override Decisions** (demonstrating governance controls): Filter by action type "override" to capture all manual PII classification changes, which are automatically logged with immutable hash chaining per [JIRA] [DPLAT-042]
   - **Data Export Activity** (relevant to data transfer standards): Use `event_type=data_export` with time ranges like `timestamp:[NOW-30d TO NOW]`

3. **Select Export Format**: Choose from CSV, Parquet, or JSON-NDJSON formats ([JIRA] [DPLAT-040]) to integrate with downstream compliance tools. The export supports configurable date ranges and filtering by tenant, user, data source, and event type.

4. **Export and Validate**: The system generates exports with encryption at rest (AES-256) and in transit (TLS 1.3), and provides access-controlled download links that expire after 24 hours ([JIRA] [DPLAT-EPIC-05]).

### Reporting Capabilities for Standards Compliance

- **Immutable Audit Trail**: All events are stored in an append-only PostgreSQL database with indefinite retention (per [CONFLUENCE] Audit Log v1 Architecture), ensuring complete historical records for standards audits.
- **PII Auto-Tagging Integration**: The Hybrid PII Classifier (v2.3) automatically tags sensitive data with confidence scores, and these classifications are captured in audit logs for standards reporting ([CONFLUENCE] Release Notes v2.3).
- **Batch Sign-Off Workflow** (planned for v2.5): Compliance officers can batch review and certify exports across tenants, generating a signed PDF certificate ([JIRA] [DPLAT-039]).

### How Compliance Is Monitored (Standards Perspective)

- **Real-Time Event Capture**: Every data access, modification, and PII override is automatically logged within 500ms, with SHA-256 hash chaining to prevent tampering ([JIRA] [DPLAT-042]).
- **Role-Based Access Control**: Only compliance officers can trigger exports, and all authorization decisions are logged to the audit trail ([JIRA] [DPLAT-REQ-10]).
- **Retention Policy Enforcement**: The default retention period is 2,555 days (7 years) for compliance tenants, configurable via the `COMPLIANCE_RETENTION_DAYS` variable ([GITHUB] compliance-vault README). A known issue ([DPLAT-DEF-04]) may cause up to 48-hour retention overruns for tenants with pre-v2.0 custom policies, with a `retention.strict_mode` workaround available.

**Key Takeaway**: To generate a standards-compliant report, use the audit log export with filters targeting PII access events and override decisions, export in your required format, and validate that the immutable audit trail captures all necessary governance actions.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Release Notes — v2.3 (April 2026)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/fc4e516f49c5)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Reporting Engine

`⚠ stale`

### How to Generate Compliance Reports

To generate compliance reports, compliance officers use the **Compliance Vault's Audit Log Export** feature. The process involves:

1. **Navigate to the Audit Log Export page** in the Compliance Vault UI (accessible via **Settings → Compliance Vault** per [$[Compliance Vault — Module Overview]$]).

2. **Configure the export parameters**:
   - **Date range**: Use the form with start date and end date fields. The system supports both absolute ISO-8601 timestamps (e.g., `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) and relative ranges (e.g., `-30d` for last 30 days) via the [$[Audit Log — Query Language Reference]$] DSL.
   - **Filters**: Apply filters by event type, actor, resource path, tenant, or custom metadata using the query DSL. For example: `event_type=data_export AND timestamp:[NOW-30d TO NOW]`.
   - **Export format**: Select from **CSV** (default), **Parquet**, or **JSON-NDJSON** via a dropdown selector, as implemented in [$[DPLAT-040]$].

3. **Trigger the export**: Submit the request. The system generates the file within **30 seconds for datasets up to 100,000 entries** (per [$[DPLAT-REQ-10]$]), and a notification email with a **secure download link** is sent. The link expires after **24 hours** (per [$[DPLAT-010]$]).

4. **Download and use the report**: The exported file includes proper headers, UTF-8 encoding, and PII field masking based on tenant configuration. For Parquet, compression ratio is approximately 60% (per [$[DPLAT-040]$]).

### Reporting Capabilities

The Reporting Engine provides the following capabilities:

- **Ad-hoc exports**: Generate reports on demand with customizable date ranges and filters ([$[DPLAT-010]$]).
- **Multiple export formats**: CSV, Parquet, and JSON-NDJSON for integration with downstream compliance and analytics tools ([$[DPLAT-040]$]).
- **Advanced filtering**: Filter by event type, actor role, IP address, bytes transferred, connector ID, and nested metadata fields (e.g., `metadata.pii_fields IN (email, ssn, phone)`) using the query DSL ([$[Audit Log — Query Language Reference]$]).
- **Aggregations**: Summarize results with `AGGREGATE: count BY actor_role` or `SUM(bytes_transferred) BY event_type` ([$[Audit Log — Query Language Reference]$]).
- **Full-text search across historical exports**: Search by keywords with highlighted snippets, filterable by date range, PII category, and workspace (in progress for v2.4, per [$[DPLAT-037]$]).
- **Batch sign-off workflow**: Select up to 50 tenant exports for batch review, add a single sign-off comment, and generate a PDF certificate marking logs as "Certified" (planned for v2.5, per [$[DPLAT-039]$]).

### How Compliance Is Monitored

Compliance monitoring is achieved through the **immutable audit trail** stored in PostgreSQL (per [$[ADR-007]$]):

- **Event capture**: Every data access, modification, permission change, configuration change, and authentication event is recorded in the `audit_events` table with fields like `event_type`, `actor_id`, `tenant_id`, `resource_type`, `action`, and `metadata` ([$[Audit Log v1 Architecture (Legacy)]$]).
- **PII override tracking**: All manual PII classification overrides are automatically captured with SHA-256 hash chaining to prevent tampering, including user ID, timestamp, original/new classification, and data source ([$[DPLAT-042]$]).
- **Access control**: Only **Compliance Officers** can trigger exports (per [$[DPLAT-REQ-10]$]), and all authorization decisions are logged to the audit trail. Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3).
- **Retention**: Audit logs are retained indefinitely in v1 (per [$[Audit Log v1 Architecture (Legacy)]$]), with the Compliance Vault configurable via `COMPLIANCE_RETENTION_DAYS` (default 2555 days, per [$[compliance-vault README]$]).
- **Querying**: Compliance officers can query events via `GET /api/v1/audit/events` or the `/api/v1/compliance/audit-query` endpoint using the DSL, with support for time-range filters, tenant isolation, and PII redaction toggles ([$[Audit Log v1 Architecture (Legacy)]$], [$[Audit Log — Query Language Reference]$]).

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)

## Report Generation

To generate compliance reports in the Compliance Vault, you use the **Audit Log Export** feature (F-B2), which provides on-demand access to immutable records of all data access and modification events across your tenant.

### How to Generate a Compliance Report

1. **Navigate** to the Audit Log Export page within the Compliance Vault module (accessible to compliance officers and workspace admins).
2. **Configure your query** using the domain-specific query language (DSL) via the `/api/v1/compliance/audit-query` endpoint or the Compliance Vault UI. You can filter by:
   - **Event type** (e.g., `data.access`, `data.modify`, `auth.login`, `config.change`)
   - **Timestamp range** using absolute ISO-8601 dates (`timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative ranges (`timestamp:[NOW-30d TO NOW]`)
   - **Actor identity** (user or service ID)
   - **Resource path** and **connector ID**
   - **Custom metadata** (e.g., `metadata.pii_fields IN (email, ssn)`)
3. **Select export format**: JSON (machine-readable), CSV (spreadsheets), or PDF (human-readable with digital signatures for legal proceedings).
4. **Submit the request**. The system generates the export and sends a notification email with a secure download link that expires after 24 hours. Export generation latency is under 5 seconds for datasets up to 10,000 records.

### Reporting Capabilities

The system supports:
- **Advanced filtering** by tenant, workspace, user role, event categories, and PII sensitivity levels
- **Aggregations** to summarize results (e.g., `AGGREGATE: count BY actor_role`, `AGGREGATE: SUM(bytes_transferred) BY event_type`)
- **Batch export** for multi-tenant environments (up to 50 tenants at once)
- **Export metadata tracking** including requestor, timestamp, record count, and retention status
- **Integration with PII auto-tagging** to highlight sensitive data access patterns in exports

### Compliance Monitoring

Compliance is monitored through the immutable audit log, which captures all events at ingestion time. The system records:
- **Data access and modification** events
- **Permission changes** and **configuration changes**
- **Authentication events** (login, logout, failed attempts)
- **PII override decisions** automatically (per [$[DPLAT-042]$])

Audit logs are retained according to the tenant's configured retention policy (default 2555 days per [$[compliance-vault]$] and [$[audit-log-service]$]), with all data encrypted at rest using AES-256 and in transit via TLS 1.3. Compliance officers can also use the batch sign-off workflow (per [$[DPLAT-039]$]) to certify multiple exports across tenants with a single digital approval.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)

## Template Management

The Compliance Vault module provides robust compliance reporting capabilities through its **Audit Log Export** feature (epic [$[DPLAT-EPIC-05]$]), which is directly relevant to Template Management. Here is how you generate compliance reports and what the reporting capabilities are:

### How to Generate Compliance Reports

1. **Access the Export UI**: Compliance officers and workspace admins initiate exports through the Compliance Vault module UI or via the API endpoint `/api/v1/compliance/audit-query`.

2. **Apply Filters**: Use the domain-specific query language (DSL) to filter audit events. For template-related compliance, you can filter by:
   - **Event type**: e.g., `config.change` for template modifications, `data.access` for template usage
   - **Actor identity**: Filter by user or service that modified templates
   - **Resource path**: Target specific template resources
   - **Time range**: Use absolute ISO-8601 timestamps or relative ranges like `-30d` (last 30 days) or `-1y` (last year)

   Example query for template management compliance:
   ```
   event_type=config.change AND resource_type=template AND timestamp:[NOW-90d TO NOW]
   ```

3. **Select Export Format**: Choose from three formats via the format selector (per [$[DPLAT-040]$]):
   - **CSV** (default) — with proper headers and UTF-8 encoding
   - **Parquet** — with schema metadata and ~60% compression ratio
   - **JSON-NDJSON** — one valid JSON object per line

4. **Trigger Export**: Only users with the **Compliance Officer** role can trigger exports (per [$[DPLAT-REQ-10]$]). Exports are delivered via encrypted download links that expire after 24 hours.

### Reporting Capabilities

- **On-demand historical exports**: Generate point-in-time reports for regulatory reviews and forensic analysis (no real-time streaming in current phase)
- **Advanced filtering**: Filter by tenant, workspace, user role, event categories, and custom metadata fields
- **Aggregation support**: Summarize results using `AGGREGATE` expressions — e.g., `AGGREGATE: count BY event_type` to see template modification frequency
- **Batch sign-off workflow** (planned for v2.5, per [$[DPLAT-039]$]): Compliance officers can batch review and sign off multiple exports across tenants, generating a PDF certificate
- **ServiceNow integration** (planned for v2.5, per [$[DPLAT-015]$]): Export findings directly to ServiceNow for ITSM ticketing

### How Compliance Is Monitored (Template Management Context)

Compliance monitoring for template management relies on the **immutable audit log** stored in the `audit_events` PostgreSQL table. Key monitoring mechanisms include:

- **Automatic capture of all PII override decisions** (per [$[DPLAT-042]$]): When workspace admins override PII auto-tagging on templates, the system automatically logs the user ID, timestamp, original classification, new classification, and data record identifier within 500ms. Each entry includes an immutable SHA-256 hash chain preventing tampering.

- **Event taxonomy coverage**: Template-related actions fall under `config.change` events, which are captured with full metadata including actor identity, tenant, and resource identifiers.

- **Retention policy**: Audit logs are retained for **2555 days** (7 years) per the compliance-vault configuration, ensuring long-term compliance monitoring capability.

- **Access control**: Only compliance officers can read all tenants' audit data; workspace admins can only read their own tenant's data. All authorization decisions are logged to the immutable audit trail.

For template-specific compliance monitoring, you can use the query DSL to track who modified templates, when, and what changes were made, then export these findings in your preferred format for regulatory reporting.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)

## Distribution

`⚠ stale`

To generate compliance reports focused on **distribution** (i.e., exporting audit log data for regulatory review), you use the **Audit Log Export** feature within the Compliance Vault module. This capability is delivered under Epic [$[DPLAT-EPIC-05]$] (Audit Log Export) and is accessible exclusively to users with the **Compliance Officer** role, as enforced by RBAC rule [$[DPLAT-REQ-10]$].

### How to Generate a Compliance Report (Distribution)

1. **Navigate** to the Audit Log Export page in the Compliance Vault UI.
2. **Set a date range** — use the form with start and end date fields to filter historical records (per [$[DPLAT-010]$]).
3. **Select an export format** — choose from **CSV** (default), **Parquet**, or **JSON-NDJSON** via the format selector (per [$[DPLAT-040]$]).
4. **Apply advanced filters** — optionally filter by user, data source, connector, event type, or tenant using the query DSL (e.g., `event_type=data_export AND timestamp:[NOW-30d TO NOW]`).
5. **Trigger the export** — the system generates the file within **30 seconds for up to 100,000 entries** (per [$[DPLAT-REQ-10]$]).
6. **Receive the download** — a notification email with a **secure, encrypted download link** (AES-256 at rest, TLS 1.3 in transit) that expires after **24 hours** (per [$[DPLAT-010]$]).

### Reporting Capabilities

- **Format flexibility**: CSV, Parquet, or JSON-NDJSON — Parquet achieves ~60% compression ratio (per [$[DPLAT-040]$]).
- **Filtering**: By event type, actor, resource path, tenant, IP address, and custom metadata fields (per the [$[Audit Log — Query Language Reference]$]).
- **Aggregations**: Summarize by actor role, event type, or data volume (e.g., `AGGREGATE: SUM(bytes_transferred) BY event_type`).
- **Export metadata**: Each export tracks requestor, timestamp, record count, and retention status (per [$[DPLAT-EPIC-05]$]).
- **PII override capture**: All manual PII classification overrides are automatically logged with SHA-256 hash chaining for tamper evidence (per [$[DPLAT-042]$]).

### How Compliance Is Monitored (Distribution Context)

- **Immutable audit trail**: All data access, modifications, and administrative actions are recorded in the `audit_events` table with append-only semantics (per [$[Audit Log v1 Architecture (Legacy)]$]).
- **Retention**: Audit logs are retained for **2555 days** (7 years) by default, configurable via `COMPLIANCE_RETENTION_DAYS` (per [$[compliance-vault — README]$]).
- **Access control**: Only Compliance Officers can trigger exports; all authorization decisions are logged to the audit trail (per [$[DPLAT-REQ-10]$]).
- **Future capabilities**: Planned features include batch sign-off workflows ([$[DPLAT-039]$]) and ServiceNow integration for automated ITSM ticketing ([$[DPLAT-015]$]).

In summary, generating a compliance report for distribution involves selecting a date range, choosing an export format, applying filters, and receiving a secure download link — all within the Compliance Vault's RBAC-protected export interface.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Release Notes — v2.3 (April 2026)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/fc4e516f49c5)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)

## Visualization

To generate compliance reports with a focus on **visualization**, you use the **Compliance Vault's Audit Log Export** feature, which is now Generally Available as of v2.3 (April 2026). The system provides multiple ways to visualize compliance data:

### Generating Visual Reports

1. **Export in Visualization-Friendly Formats**: Use the audit log export functionality to generate reports in formats suitable for visualization tools:
   - **CSV** (default) — for spreadsheet-based charts and dashboards
   - **JSON Lines (JSON-NDJSON)** — for programmatic analysis and SIEM integration
   - **Parquet** — for high-performance analytics (compression ratio ~60%)

   Example export command:
   ```bash
   dplat audit-export \
     --start "2026-01-01" \
     --end "2026-03-31" \
     --event-type "pii_access,pii_export,pii_delete" \
     --tenant "acme-corp" \
     --format jsonl \
     --output s3://compliance-bucket/audit-q1-2026/
   ```
   (per [$[Release Notes — v2.3 (April 2026)]$])

2. **Query with Aggregations for Visual Summaries**: The Audit Log Query Language (DSL) supports aggregations that can feed directly into visualization tools:
   ```
   AGGREGATE: count BY actor_role
   AGGREGATE: SUM(bytes_transferred) BY event_type
   AGGREGATE: DISTINCT(actor_id) WHERE event_type=data_export
   ```
   (per [$[Audit Log — Query Language Reference]$])

### Reporting Capabilities for Visualization

- **Filtered Data Extraction**: Apply precise filters before exporting — by event type, timestamp range, actor, resource path, or custom metadata (e.g., `metadata.pii_sensitive=true`)
- **Time-Range Selection**: Use absolute ISO-8601 dates or relative ranges like `-30d` for the last 30 days
- **Export Metadata Tracking**: Each export records requestor, timestamp, record count, and retention status for auditability
- **Secure Delivery**: Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3), with download links expiring after 24 hours (per [$[DPLAT-EPIC-05]$])

### How Compliance Is Monitored (Visualization Aspect)

Compliance monitoring is visualized through:
- **Audit Event Queries** via the Compliance Vault UI or the `/api/v1/compliance/audit-query` endpoint, which return structured data ready for charting
- **PII Override Tracking**: All manual PII classification overrides are automatically captured with immutable SHA-256 hash chaining, enabling visualization of classification change patterns over time (per [$[DPLAT-042]$])
- **Export Format Selector**: The UI provides a dropdown with CSV, Parquet, and JSON-NDJSON options, allowing compliance officers to choose the format best suited to their visualization toolchain (per [$[DPLAT-040]$])

**Note**: The batch sign-off workflow (for generating PDF certificates) and full-text search across historical exports are planned for future releases (v2.5 and v2.4 respectively) and are not yet available for visualization purposes.

**Sources:**
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Release Notes — v2.3 (April 2026)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/fc4e516f49c5)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)

## Audit Oversight

`⚠ stale`

### How to Generate Compliance Reports

To generate compliance reports for audit oversight, compliance officers use the **Compliance Vault** module's audit log export functionality. The process involves:

1. **Navigating to the Audit Log Export page** in the Compliance Vault UI, where you can specify a date range (start and end dates) and select an export format [$[DPLAT-010]$].

2. **Applying filters** using the domain-specific query language (DSL) via the `/api/v1/compliance/audit-query` endpoint or the UI. You can filter by event type, timestamp range, actor identity, resource path, and custom metadata [$[Audit Log — Query Language Reference]$]. For example:
   - `event_type=data_export AND timestamp:[NOW-30d TO NOW]` for last month's export activity
   - `actor_role=admin AGGREGATE: count BY event_type` for admin action summaries

3. **Selecting export format** from three options: CSV (default), Parquet, or JSON-NDJSON [$[DPLAT-040]$]. A full 90-day export fits within 4 GB compressed CSV per tenant [$[DPLAT-REQ-08]$].

4. **Receiving a secure download link** via email notification, which expires after 24 hours and uses pre-signed URL technology with cryptographic signature validation [$[DPLAT-038]$][$[DPLAT-010]$].

### Reporting Capabilities

The system provides comprehensive reporting capabilities:

- **Query DSL**: Supports comparison operators (`=`, `!=`, `>`, `<`, `~` for regex, `IN` for set membership), logical operators (`AND`, `OR`, `NOT`), and aggregations (`COUNT`, `SUM`, `DISTINCT`) [$[Audit Log — Query Language Reference]$].
- **Full-text search** across historical exports is being implemented (Elasticsearch-based indexing) to quickly locate specific compliance events [$[DPLAT-037]$].
- **Batch sign-off workflow** allows compliance officers to review and certify up to 50 audit log exports simultaneously, generating a PDF certificate with officer name, timestamp, and unique certificate ID [$[DPLAT-039]$].
- **ServiceNow integration** (planned) will enable automatic ITSM ticket creation from audit findings [$[DPLAT-015]$].

### How Compliance Is Monitored

Compliance monitoring for audit oversight is built on an immutable audit logging system:

- **Immutable event capture**: Every data access, modification, deletion, authentication event, configuration change, and connector synchronization is recorded in the `audit_events` PostgreSQL table with append-only semantics [$[Audit Log v1 Architecture (Legacy)]$].
- **PII override tracking**: All manual PII classification overrides are automatically captured within 500ms, including user ID, timestamp, original and new classifications, with SHA-256 hash chaining to prevent tampering [$[DPLAT-042]$].
- **Access control**: Only Compliance Officers can trigger exports (RBAC enforcement), and all authorization decisions are logged to the immutable audit trail [$[DPLAT-REQ-10]$].
- **Retention**: Audit logs are retained for 2555 days (7 years) by default, with no automatic deletion to ensure complete historical records for forensic analysis [$[audit-log-service README]$][$[Audit Log v1 Architecture (Legacy)]$].
- **Security**: All audit data is encrypted at rest (AES-256) and in transit (TLS 1.3), with exports also encrypted and access-controlled [$[Audit Log v1 Architecture (Legacy)]$][$[DPLAT-REQ-08]$].

**Key takeaway**: The system provides a complete audit oversight workflow—from querying and filtering immutable audit events, to generating secure exports in multiple formats, to batch certification and integration with external compliance tools.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)

## Review Workflows

To generate compliance reports in Review Workflows, use the Audit Log Export feature in the Compliance Vault. Set a date range, apply filters (event type, actor, tenant, etc.), and choose CSV, Parquet, or JSON-NDJSON format. The system generates a pre-signed download URL valid for 24 hours. For batch certification, use the batch sign-off workflow to sign up to 50 exports and produce a PDF certificate. Compliance is monitored via immutable audit logs, PII auto-tagging, and RBAC that restricts export to Compliance Officers only. Full-text search across historical exports is also supported.

**Sources:**
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)

## Auditor Access

`⚠ stale`

### How to Generate Compliance Reports

To generate compliance reports for auditor access, a **Compliance Officer** can use the **Audit Log Export** feature within the Compliance Vault module. The process is as follows:

1. **Navigate** to the Audit Log Export page in the Compliance Vault UI.
2. **Set a date range** — use the start and end date fields to define the period of interest. The system also supports relative time ranges such as `-30d` (last 30 days) or `-1y` (last year) via the query DSL (per [$[Audit Log — Query Language Reference]$]).
3. **Select an export format** — choose from **CSV** (default), **Parquet**, or **JSON-NDJSON** (per [$[DPLAT-040]$]).
4. **Apply optional filters** — narrow results by event type, actor, resource path, connector, or PII category using the query language (e.g., `event_type=data_export AND timestamp:[NOW-30d TO NOW]`).
5. **Trigger the export** — the system generates the file and sends a notification email with a **secure download link that expires after 24 hours** (per [$[DPLAT-010]$]).

Only users with the **Compliance Officer** role can trigger exports (per [$[DPLAT-REQ-10]$]). Exported files are encrypted at rest (AES-256) and in transit (TLS 1.3).

### Reporting Capabilities

The Compliance Vault offers the following reporting capabilities specifically relevant to auditor access:

- **Export formats**: CSV, Parquet, and JSON-NDJSON (per [$[DPLAT-040]$])
- **Query DSL**: Supports filtering by event type, timestamp range, actor identity, resource path, IP address, and custom metadata. Aggregations are available (e.g., `AGGREGATE: count BY event_type`) (per [$[Audit Log — Query Language Reference]$])
- **Full-text search**: Compliance officers can search across historical exports using keywords, with results returning within 3 seconds for datasets up to 100,000 records (per [$[DPLAT-037]$])
- **Retention and archival**: Audit logs are retained for **2,555 days (7 years)** by default (per [$[compliance-vault]$] README). Logs older than 90 days are automatically archived to **S3 Glacier** for cost-effective long-term storage, with a maximum retrieval latency of 4 hours (per [$[DPLAT-036]$])

### How Compliance Is Monitored

Compliance monitoring for auditor access is achieved through:

- **Immutable audit trail**: All data access, modification, permission changes, configuration changes, and authentication events are captured in an append-only PostgreSQL table (`audit_events`) with SHA-256 hash chaining to prevent tampering (per [$[Audit Log v1 Architecture (Legacy)]$] and [$[DPLAT-042]$])
- **PII override tracking**: Every manual override of PII classification is automatically logged with user ID, timestamp, original/new classification, and data record identifier (per [$[DPLAT-042]$])
- **Role-based access control**: Only Compliance Officers can export audit logs; Workspace Admins can view logs for their own tenant; Support requires approval (per [$[Audit Log v1 Architecture (Legacy)]$] and [$[DPLAT-REQ-10]$])
- **Retention policy enforcement**: Logs are retained for the configured period (default 2,555 days) and archived to S3 Glacier after 90 days, with daily retention summary reports (per [$[DPLAT-036]$])

In summary, auditors can request compliance reports via the Audit Log Export feature, which provides flexible filtering, multiple export formats, and secure delivery — all backed by an immutable, tamper-evident audit trail.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)

## Compliance Logs

`⚠ stale`

### How to Generate Compliance Reports

To generate compliance reports from the Compliance Logs, you use the **Audit Log Query Language (DSL)** exposed by the Compliance Vault. Queries are submitted via the `/api/v1/compliance/audit-query` endpoint or through the Compliance Vault UI [$[Audit Log — Query Language Reference]$].

**Step-by-step process:**
1. **Define a filter expression** using fields like `event_type`, `actor_id`, `actor_role`, `resource_path`, and `timestamp`.
2. **Specify a time range** using absolute ISO-8601 timestamps (e.g., `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) or relative shortcuts (e.g., `-30d` for last 30 days).
3. **Optionally apply aggregations** to summarize results, such as `AGGREGATE: count BY actor_role` or `AGGREGATE: SUM(bytes_transferred) BY event_type`.
4. **Export the results** in your preferred format — CSV, Parquet, or JSON-NDJSON — via the export format selector [$[DPLAT-040]$]. The system generates a pre-signed download URL with 24-hour expiry for secure retrieval [$[DPLAT-038]$].

**Example query for a compliance report:**
```
event_type=data_export AND timestamp:[NOW-30d TO NOW] AND actor_role=compliance-officer
```

### Reporting Capabilities

The Compliance Logs offer the following reporting capabilities:

- **Ad-hoc date range exports**: Compliance officers can trigger exports with customizable start and end dates, receiving a notification email with a secure download link [$[DPLAT-010]$].
- **Full-text search across historical exports**: An Elasticsearch-based indexing system allows keyword and phrase searches across all archived audit logs, with results returning within 3 seconds for datasets up to 100,000 records [$[DPLAT-037]$].
- **Batch sign-off workflow**: Officers can select up to 50 tenant audit log exports for batch review, add a single sign-off comment, and generate a batch sign-off certificate (PDF) with a unique certificate ID [$[DPLAT-039]$].
- **Multiple export formats**: CSV (default), Parquet (with ~60% compression ratio), and JSON-NDJSON [$[DPLAT-040]$].
- **ServiceNow integration** (planned for v2.5): Export findings directly to ServiceNow for automated ITSM ticketing with severity mapping based on PII sensitivity [$[DPLAT-015]$].

### How Compliance Is Monitored

Compliance monitoring is achieved through several mechanisms:

1. **Immutable audit trail**: Every data access, modification, and administrative action generates an audit event stored in a PostgreSQL database with append-only semantics. The system uses SHA-256 hash chaining to link entries, preventing retroactive tampering [$[DPLAT-042]$].

2. **Automatic PII override capture**: When a workspace admin overrides a PII classification, the system creates an audit log entry within 500ms containing the user ID, timestamp, original and new classifications, and data record identifier [$[DPLAT-042]$].

3. **Retention and archival**: Audit logs are retained for 2555 days (7 years) by default [$[audit-log-service README]$]. Logs older than 90 days are automatically archived to S3 Glacier for cost-effective long-term storage, with a maximum retrieval latency of 4 hours for querying [$[DPLAT-036]$].

4. **Access control**: Only system accounts can insert events; workspace admins can read their own tenant's logs; compliance officers can read all tenants; support requires approval [$[Audit Log v1 Architecture (Legacy)]$].

5. **Security**: All audit data is encrypted at rest using AES-256 and in transit via TLS 1.3. IP addresses are redacted to /24 subnet for privacy [$[Audit Log — Query Language Reference]$].

**Key monitoring queries** include tracking failed logins by IP range, high-volume data transfers (>100MB), and admin actions summarized by event type — all accessible through the query DSL with a maximum of 100,000 events per query.

**Sources:**
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)

## Reporting

To generate compliance reports in the Amisol DataPlatform, you use the **Compliance Vault (MOD-B)** module, which provides two primary mechanisms for reporting on audit log data.

### How to Generate Compliance Reports

**1. Ad-Hoc Exports via the Compliance Vault UI**

Compliance officers can trigger on-demand exports of audit logs with customizable date ranges. Navigate to the **Audit Log Export** page within the Compliance Vault, where you can:
- Select a **start date** and **end date** to define the reporting period
- Choose an **export format** (CSV, JSON, or PDF)
- Apply advanced filters by user, data source, connector, and event type

Once submitted, the system generates the report and sends a notification email with a **secure download link that expires after 24 hours** (per [$[DPLAT-010]$]).

**2. Query-Based Reporting via the Audit Log DSL**

For more targeted reports, compliance officers can use the **domain-specific query language (DSL)** via the `/api/v1/compliance/audit-query` endpoint. This allows filtering by:
- **Event type** (e.g., `data_export`, `login`, `config.change`)
- **Timestamp ranges** (absolute ISO-8601 or relative shortcuts like `-30d`)
- **Actor identity** and role
- **Resource path** and custom metadata

Example query for export activity in the last month:
```
event_type=data_export AND timestamp:[NOW-30d TO NOW]
```

Aggregations are also supported, such as counting events by actor role or summing data transfer volumes by event type (per [$[Audit Log — Query Language Reference]$]).

### Reporting Capabilities

| Capability | Details |
|------------|---------|
| **Export Formats** | CSV, JSON, PDF (PDF includes digital signatures for legal proceedings) |
| **Filtering** | By tenant, workspace, user role, event categories, date range |
| **Batch Export** | Multi-tenant environments supported (up to 50 tenants per batch) |
| **Batch Sign-Off** | Compliance officers can batch review and sign off multiple exports, generating a single PDF certificate (per [$[DPLAT-039]$]) |
| **PII Highlighting** | Exports integrate with PII auto-tagging to highlight sensitive data access patterns |
| **ServiceNow Integration** | Planned capability to export findings directly to ServiceNow for ITSM ticketing (per [$[DPLAT-015]$]) |
| **Performance** | Export generation under 5 seconds for datasets up to 10,000 records |

### How Compliance Is Monitored

Compliance monitoring is achieved through the **immutable audit log** stored in PostgreSQL (or optionally ClickHouse). The system captures all data access, modification, permission changes, configuration changes, and authentication events. Key monitoring features include:

- **Real-time event capture**: Every connector, API call, and user action generates an audit event that flows into the central database
- **Retention policy**: Audit logs are retained for **2,555 days (7 years)** by default, configurable per tenant
- **PII override tracking**: All manual PII classification overrides are automatically logged with SHA-256 hash chaining to prevent tampering (per [$[DPLAT-042]$])
- **Access control**: Only compliance officers can view all tenants' logs; workspace admins see only their own tenant

The system supports regulatory requirements under **GDPR** and **German BDSG**, ensuring data residency controls and automated PII detection at ingestion time.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)

## Risk Management

`⚠ stale`

### Generating Compliance Reports

To generate compliance reports for risk management, compliance officers use the **Audit Log Export** feature (epic [$[DPLAT-EPIC-05]$]) within the MOD-B Compliance Vault module. The process involves:

1. **Querying audit events** via the `/api/v1/compliance/audit-query` endpoint or the Compliance Vault UI, using a domain-specific query language (DSL) that supports filtering by event type, timestamp range, actor identity, resource path, and custom metadata (per [$[Audit Log — Query Language Reference]$]).

2. **Selecting export format** — CSV, Parquet, or JSON-NDJSON — via a dropdown selector (implemented in [$[DPLAT-040]$]), with CSV as the default.

3. **Initiating the export** through the Compliance Vault UI, which generates an on-demand export with configurable date range filtering. Exports are delivered with encryption at rest (AES-256) and access-controlled download links that expire after 24 hours (per [$[DPLAT-EPIC-05]$]).

**Access control**: Only users with the **Compliance Officer** role can trigger exports, as enforced by RBAC requirement [$[DPLAT-REQ-10]$]. Workspace admins can read audit events for their own tenant, but export initiation is restricted to compliance officers.

### Reporting Capabilities

The system provides the following reporting capabilities relevant to risk management:

| Capability | Description | Source |
|------------|-------------|--------|
| **Filtering** | By event type, timestamp (absolute ISO-8601 or relative like `-30d`), actor, resource path, IP address, connector, tenant, and nested metadata fields | [$[Audit Log — Query Language Reference]$] |
| **Aggregations** | Count, SUM, DISTINCT across fields (e.g., `AGGREGATE: count BY actor_role`) | [$[Audit Log — Query Language Reference]$] |
| **Full-text search** | Across historical exports using Elasticsearch-based indexing, returning results within 3 seconds for up to 100,000 records | [$[DPLAT-037]$] |
| **Batch sign-off** | Compliance officers can batch review and digitally sign up to 50 tenant exports, generating a PDF certificate with unique ID | [$[DPLAT-039]$] |
| **ServiceNow integration** | Direct export to ServiceNow for automatic ITSM ticket creation, with severity mapping based on PII sensitivity level | [$[DPLAT-015]$] (status: To Do) |
| **Export metadata tracking** | Each export records requestor, timestamp, record count, and retention status | [$[DPLAT-EPIC-05]$] |

### How Compliance Is Monitored

Compliance monitoring for risk management relies on the **immutable audit trail** captured by the audit-log-service (feature F-B2) and the **PII Auto-Tagging** engine (feature F-B1):

1. **Continuous event capture**: Every data access, modification, deletion, authentication event, configuration change, and connector synchronization generates an audit event stored in the `audit_events` PostgreSQL table (per [$[Audit Log v1 Architecture (Legacy)]$]). The system uses an append-only model with SHA-256 hash chaining to prevent tampering (per [$[DPLAT-042]$]).

2. **PII detection at ingestion**: The hybrid rule+ML detection engine automatically identifies PII during data ingestion, with confidence scoring (threshold 0.75). All classification events are logged, including override decisions by workspace admins (per [$[PII Auto-Tagging — Policy and Behavior]$] and [$[DPLAT-042]$]).

3. **Retention policy enforcement**: PII-tagged data has a platform-wide default retention period of **30 days**, after which data is automatically anonymized or deleted. The audit log itself retains events indefinitely (per [$[Audit Log v1 Architecture (Legacy)]$]), while the compliance vault service uses a configurable retention period of **2555 days** (7 years) as shown in the compliance-vault configuration (per [$[compliance-vault README]$]).

4. **Data residency controls**: PII data is subject to region-aware routing (EU, DE, US regions) with strict controls under GDPR Art. 44 and BDSG, ensuring sensitive data never leaves its designated region without explicit consent (per [$[PII Auto-Tagging — Policy and Behavior]$]).

5. **Access control monitoring**: All authorization decisions (including export requests) are logged to the immutable audit trail, providing a complete record of who accessed what data and when (per [$[DPLAT-REQ-10]$]).

**Key risk management insight**: The combination of automatic PII tagging at ingestion, immutable audit logging with hash chaining, and configurable retention policies enables compliance officers to demonstrate regulatory compliance through auditable, tamper-evident records — directly supporting risk mitigation for data protection regulations like GDPR and CCPA.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Risk Assessment

`⚠ stale`

The Compliance Vault provides a comprehensive audit logging and reporting system designed specifically for risk assessment and regulatory compliance. Here is how compliance reporting works for risk assessment purposes:

### Generating Compliance Reports

To generate compliance reports, you use the **Audit Log Export** feature. As a **compliance officer**, you can trigger ad-hoc exports by navigating to the Audit Log Export page and specifying a date range (start and end dates) along with your preferred export format [$[DPLAT-010]$]. The system then generates a file containing all audit log entries within that range, including timestamps, user identities, actions performed, data sources, and affected PII fields [$[DPLAT-010]$].

The export process is restricted to the **Compliance Officer role only** via RBAC controls, ensuring that only authorized personnel can access sensitive audit data [$[DPLAT-REQ-10]$]. Exported files are encrypted at rest using AES-256 and transmitted over TLS 1.3 [$[DPLAT-REQ-10]$]. Once the export completes, you receive a notification email with a secure download link that expires after 24 hours [$[DPLAT-010]$].

### Reporting Capabilities

The system offers several key reporting capabilities for risk assessment:

- **Flexible Export Formats**: You can export audit logs in CSV (default), Parquet, or JSON-NDJSON formats, allowing integration with downstream compliance and analytics tools [$[DPLAT-040]$].
- **Advanced Filtering**: The query DSL supports filtering by event type, timestamp range, actor identity, resource path, and custom metadata. You can use comparison operators (`=`, `!=`, `>`, `<`, `IN`, `~` for regex) and logical operators (`AND`, `OR`, `NOT`) [$[Audit Log — Query Language Reference]$].
- **Aggregation Capabilities**: You can summarize results using aggregations like `count BY actor_role`, `SUM(bytes_transferred) BY event_type`, or `DISTINCT(actor_id)` for specific event types [$[Audit Log — Query Language Reference]$].
- **Full-Text Search**: Compliance officers can perform full-text search across historical audit log exports to quickly locate specific compliance events, with results returning within 3 seconds for datasets up to 100,000 records [$[DPLAT-037]$].
- **Batch Sign-Off**: For quarterly compliance certifications, you can batch review and sign off up to 50 tenant audit log exports at once, generating a PDF certificate with digital approval [$[DPLAT-039]$].

### How Compliance is Monitored

Compliance monitoring is achieved through **immutable audit logging** that captures all data access and modification events across the platform. The system uses an append-only event capture mechanism where every connector, data pipeline, and user action generates audit events stored in a central PostgreSQL database [$[Audit Log v1 Architecture (Legacy)]$].

Key monitoring capabilities include:

- **Automatic PII Override Capture**: All manual PII classification overrides are automatically logged within 500ms, including the user ID, timestamp, original classification, new classification, and data record identifier. Each entry includes an immutable SHA-256 hash linking to the previous entry, preventing retroactive tampering [$[DPLAT-042]$].
- **Event Taxonomy**: The system recognizes event categories including `data.access`, `data.modify`, `data.delete`, `auth.login`, `auth.logout`, `config.change`, and `connector.sync` [$[Audit Log v1 Architecture (Legacy)]$].
- **Retention Policy**: Audit logs are retained for **2555 days** (approximately 7 years) by default, as configured in both the compliance-vault and audit-log-service [$[compliance-vault README]$][$[audit-log-service README]$].
- **Schema Versioning**: The audit log schema supports backward compatibility for at least 2 prior schema versions, ensuring historical queries remain functional for up to 2 years of retention period [$[DPLAT-REQ-20]$].

For risk assessment specifically, compliance officers can use the query DSL to filter for high-risk events such as large data transfers (`bytes_transferred>100000000`), failed login attempts, or PII access by specific connectors, enabling targeted risk analysis and forensic investigations [$[Audit Log — Query Language Reference]$].

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)

## Gap Analysis

`⚠ stale`

### How to Generate Compliance Reports

To generate compliance reports, a **Compliance Officer** uses the **Compliance Vault** module's audit log export functionality. The primary method is through the `/api/v1/compliance/audit-query` endpoint or the Compliance Vault UI, where you submit queries using a domain-specific query language (DSL) [$[Audit Log — Query Language Reference]$].

**Step-by-step process:**
1. **Access**: Only users with the **Compliance Officer** role can trigger exports (per [$[DPLAT-REQ-10]$]).
2. **Filter**: Use the query DSL to specify criteria such as event type, timestamp range, actor identity, and resource path. For example: `event_type=data_export AND timestamp:[NOW-30d TO NOW]` [$[Audit Log — Query Language Reference]$].
3. **Select Format**: Choose from CSV (default), Parquet, or JSON-NDJSON via a dropdown selector [$[DPLAT-040]$].
4. **Execute**: Submit the request. For datasets up to 10,000 records, export generation completes in under 5 seconds [$[DPLAT-EPIC-05]$]. For up to 100,000 entries, the export completes within 30 seconds [$[DPLAT-REQ-10]$].
5. **Download**: A secure download link is emailed, which expires after 24 hours [$[DPLAT-010]$].

### Reporting Capabilities

The system offers the following reporting capabilities:

- **Ad-hoc date range exports**: Compliance officers can trigger exports with customizable start and end dates [$[DPLAT-010]$].
- **Advanced filtering**: Filter by event type, user, data source (connector), tenant, workspace, user role, and event categories [$[DPLAT-EPIC-05]$].
- **Full-text search**: Search across historical audit log exports using keywords, with results returning within 3 seconds for datasets up to 100,000 records [$[DPLAT-037]$].
- **Aggregations**: Summarize results using `AGGREGATE` commands (e.g., `count BY actor_role`, `SUM(bytes_transferred) BY event_type`) [$[Audit Log — Query Language Reference]$].
- **Batch sign-off**: Compliance officers can batch review and sign off up to 50 tenant audit log exports, generating a PDF certificate with a unique certificate ID [$[DPLAT-039]$].
- **Export format flexibility**: CSV, Parquet, and JSON-NDJSON formats are supported, with Parquet achieving ~60% compression ratio [$[DPLAT-040]$].

### How Compliance Is Monitored

Compliance monitoring is achieved through an **immutable audit trail** that captures all data access and modification events:

- **Automatic capture**: Every connector, data pipeline, and user action generates audit events stored in a central PostgreSQL database (or ClickHouse as an alternative backend) [$[Audit Log v1 Architecture (Legacy)]$][$[audit-log-service]$].
- **PII override tracking**: When a workspace admin overrides a PII classification, the system automatically creates an audit log entry within 500ms, including user ID, timestamp, original and new classifications, and an immutable SHA-256 hash linking to the previous entry [$[DPLAT-042]$].
- **Retention policy**: Audit logs are retained for **2555 days** (approximately 7 years) by default, as configured in both the `compliance-vault` and `audit-log-service` [$[compliance-vault]$][$[audit-log-service]$].
- **Access control**: Only Compliance Officers can read all tenants' audit data; Workspace Admins can read only their own tenant [$[Audit Log v1 Architecture (Legacy)]$].
- **PII auto-detection**: The PII Classifier Service automatically detects and tags sensitive data (email, SSN, credit card numbers, etc.) with a confidence threshold of 0.8, feeding into the compliance pipeline [$[pii-classifier-service]$][$[DPLAT-EPIC-04]$].

### Gap Analysis Summary

| Capability | Status | Gap |
|------------|--------|-----|
| Ad-hoc date range exports | ✅ Done (v2.3) | None |
| Export format selector (CSV/Parquet/JSON-NDJSON) | ✅ Done (v2.3) | None |
| Full-text search across historical exports | 🔄 In Progress (v2.4) | Not yet available |
| Batch sign-off workflow | 📋 To Do (v2.5) | Not yet implemented |
| PII override audit capture | ✅ Done (v2.3) | None |
| RBAC for export triggering | ✅ Done (v2.3) | None |
| Training-set versioned model registry | 🔄 In Progress (v2.4) | Not yet available |

**Key gaps**: Full-text search across historical exports and the batch sign-off workflow are not yet available, limiting the efficiency of large-scale compliance reviews. The training-set versioned model registry is also in progress, which will enhance audit-ready provenance for machine learning models.

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)

## Mitigation

To generate compliance reports as a mitigation measure, you use the **Compliance Vault's Audit Log Export** feature (F-B2), which provides immutable records of all data access and modification events across your tenant. Here is the specific workflow:

### How to Generate a Compliance Report

1. **Access the Export Interface**: Navigate to the Compliance Vault module. Only users with the **Compliance Officer** role can trigger exports, as enforced by RBAC ([JIRA] DPLAT-REQ-10).

2. **Set Date Range**: Use the ad-hoc export form to specify a start and end date. The system supports both absolute ISO-8601 timestamps (e.g., `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`) and relative ranges (e.g., `-30d` for the last 30 days) ([CONFLUENCE] Audit Log — Query Language Reference).

3. **Apply Filters**: Narrow results using the query DSL. For example, to focus on data exports involving PII:
   ```
   event_type=data_export AND metadata.pii_sensitive=true AND timestamp:[NOW-30d TO NOW]
   ```
   You can filter by event type, actor, resource path, connector, and custom metadata fields.

4. **Select Export Format**: Choose from **CSV** (default), **Parquet**, or **JSON-NDJSON** ([JIRA] DPLAT-040). Parquet offers ~60% compression for large datasets.

5. **Trigger Export**: Submit the request. The system generates the file within 30 seconds for datasets up to 100,000 entries ([JIRA] DPLAT-REQ-10). You receive a notification email with a secure download link that expires after 24 hours ([JIRA] DPLAT-010).

### Reporting Capabilities

- **Export Formats**: CSV (with proper headers and UTF-8 encoding), Parquet (typed columns with schema metadata), and JSON-NDJSON (one valid JSON object per line) ([JIRA] DPLAT-040).
- **Aggregations**: Summarize results using the query DSL, e.g., `AGGREGATE: count BY actor_role` or `AGGREGATE: SUM(bytes_transferred) BY event_type` ([CONFLUENCE] Audit Log — Query Language Reference).
- **Full-Text Search**: Search across historical exports using keywords, with results returning within 3 seconds for up to 100,000 records ([JIRA] DPLAT-037).
- **Batch Sign-Off**: Compliance officers can review and certify up to 50 tenant exports at once, generating a PDF certificate with digital approval ([JIRA] DPLAT-039).

### How Compliance Is Monitored

- **Immutable Audit Trail**: All events (data access, modification, permission changes, PII overrides) are captured in the `audit_events` table in PostgreSQL, with SHA-256 hash chaining to prevent tampering ([CONFLUENCE] Audit Log v1 Architecture; [JIRA] DPLAT-042).
- **PII Auto-Tagging**: The system automatically detects and tags PII at ingestion time using pattern matching and ML classifiers, with all override decisions logged ([CONFLUENCE] Compliance Vault — Module Overview).
- **Retention**: Audit logs are retained for 2,555 days (7 years) by default, stored indefinitely in the current architecture ([GITHUB] compliance-vault; [CONFLUENCE] Audit Log v1 Architecture).
- **Access Control**: Only Compliance Officers can view all tenants' logs; Workspace Admins see only their own tenant. All authorization decisions are themselves logged to the audit trail ([JIRA] DPLAT-REQ-10).

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)

## Compliance Audit

`⚠ stale`

### How to Generate Compliance Reports

To generate compliance reports for audit purposes, compliance officers can use the **Compliance Vault** module's audit log export capabilities. The primary method is through the **ad-hoc export** feature, which allows you to trigger an export with a customizable date range [$[DPLAT-010]$]. Navigate to the Audit Log Export page, where you will see a form with start date, end date, and export format options. After submitting your request, the system generates the report and sends a notification email with a secure download link that expires after 24 hours [$[DPLAT-010]$][$[DPLAT-038]$].

For more targeted queries, you can use the **Audit Log Query Language (DSL)** via the `/api/v1/compliance/audit-query` endpoint or the Compliance Vault UI [$[Audit Log — Query Language Reference]$]. This DSL supports filtering by event type, timestamp range, actor identity, resource path, and custom metadata. For example, to review all data export activity in the last month, you would submit: `event_type=data_export AND timestamp:[NOW-30d TO NOW]` [$[Audit Log — Query Language Reference]$].

### Reporting Capabilities

The system offers several key reporting capabilities:

- **Export Formats**: Compliance officers can select from **CSV, Parquet, or JSON-NDJSON** formats, with CSV as the default [$[DPLAT-040]$]. Parquet achieves approximately 60% compression ratio for efficient storage [$[DPLAT-040]$].
- **Filtering Options**: Reports can be filtered by tenant, workspace, user role, event categories, date range, and PII sensitivity [$[DPLAT-EPIC-05]$][$[Audit Log — Query Language Reference]$].
- **Aggregations**: The query DSL supports aggregations such as `count BY actor_role` or `SUM(bytes_transferred) BY event_type` to summarize findings [$[Audit Log — Query Language Reference]$].
- **Full-Text Search**: An Elasticsearch-based indexing feature (in progress) will enable full-text search across historical exports, returning results within 3 seconds for datasets up to 100,000 records [$[DPLAT-037]$].
- **Batch Sign-Off**: A planned workflow (status: To Do) will allow compliance officers to batch review and sign off up to 50 audit log exports, generating a PDF certificate with digital approval [$[DPLAT-039]$].
- **ServiceNow Integration**: A planned feature will enable direct export to ServiceNow for automatic ITSM ticket creation based on findings [$[DPLAT-015]$].

### How Compliance Is Monitored

Compliance monitoring is built on an **immutable audit logging system** that captures all data access and modification events across the DPLAT platform [$[Audit Log v1 Architecture (Legacy)]$]. Key monitoring mechanisms include:

- **Event Capture**: Every connector, data pipeline, and user action generates audit events that flow into a central PostgreSQL database (or ClickHouse, configurable) [$[Audit Log v1 Architecture (Legacy)]$][$[audit-log-service — README]$]. Events are categorized into types such as `data.access`, `data.modify`, `data.delete`, `auth.login`, and `config.change` [$[Audit Log v1 Architecture (Legacy)]$].
- **PII Override Tracking**: All manual PII classification overrides are automatically captured in the audit log within 500ms, with SHA-256 hash chaining to prevent retroactive tampering [$[DPLAT-042]$].
- **Retention Policy**: Audit logs are retained for **2555 days (approximately 7 years)** by default, with no automatic deletion in the legacy v1 architecture [$[audit-log-service — README]$][$[compliance-vault — README]$][$[Audit Log v1 Architecture (Legacy)]$].
- **Access Control**: Compliance officers have read access to all tenants' audit data, while workspace admins can only view their own tenant's records. All data is encrypted at rest (AES-256) and in transit (TLS 1.3) [$[Audit Log v1 Architecture (Legacy)]$].
- **Export Performance**: A full 90-day export for tenants with up to 100,000 daily events completes within 5 minutes and produces a compressed CSV under 4 GB [$[DPLAT-REQ-08]$].

**Sources:**
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-040] Audit Log — export format selector (CSV / Parquet / JSON-NDJSON)](https://demo-jira.local/browse/DPLAT-040)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-015] Audit Log Export — ServiceNow integration for ITSM ticketing of findings](https://demo-jira.local/browse/DPLAT-015)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
