# 4.3  Integrity verification

> Ensuring audit logs have not been tamampered with.

## Verification Methods

`⚠ conflict`

### How to Verify Log Integrity

The audit log system implements **cryptographic hash chaining** to ensure tamper detection, as specified in [$[DPLAT-REQ-09]$]. Every audit record is cryptographically linked to its predecessor using **SHA-256** (or stronger) hash functions, with hash keys stored in an HSM certified to **FIPS 140-2 Level 3**. This creates an immutable chain where any modification to a historical record would break the hash linkage.

To verify integrity:
1. **Hash chain validation**: The system can recompute the hash chain from any starting point and compare it against the stored chain. Any discrepancy indicates tampering.
2. **Export verification**: When exporting audit logs, the system generates a **signed manifest** containing a SHA-256 hash of the exported data, an RSA-2048 digital signature, and the export timestamp (per [$[DPLAT-014]$]). A "Verify Export" button allows compliance officers to validate the manifest signature and confirm archive integrity without decryption.
3. **Pre-signed URL validation**: Downloads via pre-signed URLs include cryptographic signature validation that prevents URL forgery or tampering (per [$[DPLAT-038]$]).

The hash chain computation adds **no more than 50ms overhead per entry** and supports up to **10,000 entries per second per tenant**, with 99.95% availability during read operations.

### Audit Log Retention Period

The retention configuration is multi-layered:

| Layer | Duration | Details |
|-------|----------|---------|
| **Default retention** | **2555 days (~7 years)** | Set via `AUDIT_RETENTION_DAYS` in the audit-log-service and `COMPLIANCE_RETENTION_DAYS` in compliance-vault |
| **Hot storage** | **90 days** | After 90 days, logs are archived to **S3 Glacier** cold storage (per [$[DPLAT-036]$]) |
| **Per-tenant override** | **30–365 days** | Workspace admins can configure custom retention per tenant (min 30 days, max 365 days) |
| **PII-tagged data** | **30 days** | PII-tagged data has a separate 30-day retention before automatic anonymization/deletion |

Note: The Engineering Offsite notes mention a "90-day" retention under review, but the current configuration defaults to **2555 days** with archival to S3 Glacier after 90 days.

### How to Check for Log Gaps

To detect gaps in the audit log:

1. **Hash chain continuity**: Since every record is hash-chained, any missing record would break the chain. The system can detect gaps by verifying that each record's hash correctly references the previous record's hash.
2. **Query-based gap detection**: Use the Audit Log Query DSL to check for missing time ranges. For example, query for a specific time window and compare expected event counts against actual results. The query language supports time-range filters like `timestamp:[NOW-30d TO NOW]`.
3. **Export integrity checks**: When exporting logs, the signed manifest includes the record count and hash. If the export is incomplete or has gaps, the hash validation will fail.
4. **Retention boundary checks**: Queries older than the tenant's retention policy return empty results, which could indicate logs have been archived or deleted per policy. The system generates daily retention summary reports showing the count of logs archived and any failed archival operations (per [$[DPLAT-036]$]).

**Key limitation**: Queries are capped at **100,000 events per request**, so for large datasets, you may need to paginate or use aggregations to detect gaps across the full dataset.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)

## Checksum Validation

`⚠ stale`

To verify audit log integrity through checksum validation, the system implements **hash-chained entries** as specified in [$[DPLAT-REQ-09]$] and implemented in [$[DPLAT-029]$]. Each audit log record contains a cryptographic hash of the **previous entry**, creating an unbroken chain that makes undetected tampering computationally infeasible.

### How to Verify Log Integrity

1. **Hash Chain Verification**: Each audit log entry includes a SHA-256 (or stronger) cryptographic hash of the preceding entry. To verify integrity, you must:
   - Retrieve the complete chain of audit records for the period in question
   - Recompute the hash for each entry using the previous entry's data
   - Compare the computed hash against the stored hash in the subsequent entry
   - Any mismatch indicates tampering or corruption

2. **Digital Signature Validation**: Per [$[DPLAT-029]$], each audit log entry includes a digital signature that can be verified by the compliance officer. The hash keys are stored in an HSM with FIPS 140-2 Level 3 certification (per [$[DPLAT-REQ-09]$]).

3. **Performance Constraints**: Hash chain computation adds no more than **50ms overhead per entry**, and the system supports verification for up to **10,000 entries per second per tenant** (per [$[DPLAT-REQ-09]$]).

### Audit Log Retention Period

The retention configuration is as follows:
- **Default retention**: **2555 days (7 years)** — as configured via `AUDIT_RETENTION_DAYS` in the audit-log-service (per [$[audit-log-service]$] README) and `COMPLIANCE_RETENTION_DAYS` in the compliance-vault (per [$[compliance-vault]$] README)
- **Hot storage**: 90 days in PostgreSQL (per [$[DPLAT-036]$])
- **Cold storage**: After 90 days, logs are automatically archived to **S3 Glacier** (per [$[DPLAT-036]$])
- **Customization**: Workspace admins can configure per-tenant retention between **30 and 365 days** (per [$[DPLAT-036]$] acceptance criteria)

### How to Check for Log Gaps

To detect gaps in the audit log:

1. **Hash Chain Breaks**: The most reliable method — if you encounter an entry whose hash does not match the previous entry's computed hash, or if the chain sequence number jumps unexpectedly, a gap exists.

2. **Sequence Analysis**: The hash chain inherently creates a sequential dependency. Missing entries will manifest as:
   - A hash mismatch when verifying the entry immediately after the gap
   - An inability to reconstruct the chain across the missing period

3. **Archival Retrieval**: If logs have been archived to S3 Glacier (after 90 days), retrieval may take up to **4 hours** (per [$[DPLAT-036]$] acceptance criteria). Gaps may appear during this retrieval window but are temporary.

4. **Query Limitations**: The audit log query DSL (per [$[Audit Log — Query Language Reference]$]) supports time-range queries. If a query returns fewer events than expected for a given period, cross-reference with the hash chain to confirm whether events are missing or simply filtered.

**Important**: The v1 legacy architecture (per [$[Audit Log v1 Architecture (Legacy)]$]) did **not** implement hash-chaining. If you are verifying logs that predate the v2 migration (implemented in [$[DPLAT-029]$]), those entries will not have cryptographic integrity guarantees. The migration script for v1-to-v2 conversion has been tested with 500K legacy entries (per [$[DPLAT-029]$] comments).

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)

## Digital Signatures

`⚠ stale`

### How to Verify Log Integrity via Digital Signatures

The audit log system implements **hash-chained entries** with **digital signatures** to ensure tamper-evident integrity. According to [JIRA] DPLAT-REQ-09, every audit log record is cryptographically linked using SHA-256 hash chains, with hash keys stored in an HSM certified to FIPS 140-2 Level 3. The hash chain computation adds no more than 50ms overhead per entry and supports up to 10,000 entries per second per tenant.

Per [JIRA] DPLAT-029, the v2 architecture (which replaced the legacy v1 single-table design) implements hash-chained entries where **each entry includes a cryptographic hash of the previous entry**, preventing undetectable tampering. Each audit log entry also includes a **digital signature that can be verified by the compliance officer**.

To verify integrity:
1. **Hash chain verification**: Each entry's hash must match the hash stored in the subsequent entry. This creates an unbroken chain from the first to the most recent record.
2. **Digital signature verification**: Each entry's digital signature can be independently verified using the platform's public key, confirming the entry was created by an authorized system component and has not been modified since signing.
3. **Export verification**: When exporting audit logs (per [JIRA] DPLAT-014), the export generates a `.zip` archive containing the audit log CSV and a `manifest.json` file. The manifest includes a SHA-256 hash of the CSV, export timestamp, tenant identifier, and an **RSA-2048 digital signature** verifiable via the platform's public key. A "Verify Export" button allows compliance officers to validate the manifest signature and confirm archive integrity without decryption.

### Audit Log Retention Period

The retention period is **2555 days (approximately 7 years)** as configured by the `AUDIT_RETENTION_DAYS` environment variable in the audit-log-service (per [GITHUB] audit-log-service README). The Compliance Vault configuration also specifies `COMPLIANCE_RETENTION_DAYS = 2555` (per [GITHUB] compliance-vault README).

However, there is a separate archival mechanism: per [JIRA] DPLAT-036, audit logs older than **90 days** are automatically archived to **S3 Glacier** for cost-effective long-term storage. Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of 4 hours. Workspace admins can configure custom retention periods per tenant, with a minimum of 30 days and maximum of 365 days for the hot storage phase before archival.

Note: The legacy v1 architecture (per [CONFLUENCE] Audit Log v1 Architecture) stated indefinite retention with no automatic deletion, but this has been superseded by the v2 architecture with its 2555-day retention and 90-day archival policy.

### How to Check for Log Gaps

To check for gaps in the audit log, you can use the **hash chain verification** mechanism. Since each entry contains the cryptographic hash of the previous entry, any missing or tampered record will break the chain. The system's integrity verification process will detect:

1. **Missing entries**: If a record is deleted, the hash chain will show a discontinuity because the hash stored in the next entry will not match the hash of the previous entry.
2. **Tampered entries**: If a record is modified, its hash will change, breaking the chain link to the subsequent entry.
3. **Reordered entries**: The sequential nature of the hash chain ensures chronological ordering; any reordering would be detected.

For exported logs, the signed manifest (per [JIRA] DPLAT-014) includes the SHA-256 hash of the entire CSV, allowing verification that no records were added, removed, or modified after export. The "Verify Export" tool validates the manifest signature and confirms archive integrity without requiring decryption.

Additionally, the audit log query DSL (per [CONFLUENCE] Audit Log — Query Language Reference) supports time-range queries that can help identify temporal gaps by comparing expected event frequencies against actual records.

**Sources:**
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Hash Comparison

To verify audit log integrity using **Hash Comparison**, you rely on the cryptographic hash-chaining mechanism implemented in the Compliance Vault's audit log service (v2 architecture). Here's how it works:

### How Hash Chaining Ensures Integrity

Each audit log entry contains a **SHA-256 cryptographic hash** of the **previous entry**, creating an unbroken chain. This means that if any record is tampered with, its hash will no longer match the "previous hash" stored in the subsequent record, immediately breaking the chain. According to [JIRA] [$[DPLAT-REQ-09]$], this hash computation must add no more than 50ms overhead per entry and support up to 10,000 entries per second per tenant. The hash keys are stored in an HSM with FIPS 140-2 Level 3 certification.

### How to Perform Hash Comparison Verification

1. **Query the audit log** using the Compliance Vault's query DSL (via `/api/v1/compliance/audit-query` or the UI). For example, to retrieve a specific time range:
   ```
   timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]
   ```

2. **Extract the hash chain** from the returned records. Each entry includes:
   - Its own cryptographic hash (SHA-256)
   - The hash of the previous entry in the chain

3. **Recompute and compare**: For each record, recompute the SHA-256 hash of the previous record's content and compare it to the "previous hash" stored in the current record. If they match, the chain is intact. If any mismatch is found, tampering has occurred.

4. **For exported logs**: When you export audit logs (via the encrypted archive format described in [$[DPLAT-014]$]), the export includes a **signed manifest** containing a SHA-256 hash of the CSV file and an RSA-2048 digital signature. After export, use the **"Verify Export"** button to validate the manifest signature and confirm archive integrity without decryption.

### Checking for Log Gaps

Hash comparison also helps detect gaps. If a record is missing from the chain, the "previous hash" in the next record will not match any existing record's hash. This indicates a deletion or gap. You can also use the query DSL to filter by timestamp ranges and look for missing intervals.

### Audit Log Retention Period

The audit log retention period is **2555 days** (approximately 7 years), as configured by the `AUDIT_RETENTION_DAYS` environment variable in the audit-log-service (per [$[GITHUB] audit-log-service — README$]) and the `COMPLIANCE_RETENTION_DAYS` variable in the compliance-vault service. However, per [$[CONFLUENCE] ADR-007$], the hot storage retention is 12 months, after which logs are archived per tenant retention policy. Additionally, logs older than 90 days are automatically archived to S3 Glacier (per [$[JIRA] DPLAT-029$]).

### Summary

To verify log integrity via hash comparison: retrieve the hash-chained records, recompute hashes for each entry, and compare against the stored "previous hash" values. Use the "Verify Export" tool for exported archives. Any mismatch or missing hash link indicates tampering or a gap.

**Sources:**
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)

## Integrity Checks

`⚠ stale`

### How to Verify Log Integrity

Audit log integrity is maintained through **cryptographic hash-chaining**, as specified in requirement [$[DPLAT-REQ-09]$]. Every audit log entry includes a SHA-256 cryptographic hash of the previous entry, creating an immutable chain that prevents undetected tampering. According to [$[DPLAT-029]$], the v2 architecture implements this hash-chaining such that "each entry includes a cryptographic hash of the previous entry, preventing undetectable tampering."

To verify integrity:
1. **Hash chain verification**: Each audit log entry contains a digital signature that compliance officers can verify. The system supports linear scaling for verification across workspaces with up to 100 million historical records (per [$[DPLAT-REQ-09]$]).
2. **Digital signature validation**: Each entry includes a digital signature stored with hash keys in an HSM with FIPS 140-2 Level 3 certification.
3. **Performance constraints**: Hash chain computation adds no more than 50ms overhead per entry, and the system supports up to 10,000 hash-chained entries per second per tenant.

The v2 architecture replaced the legacy v1 single-table design (documented in [$[Audit Log v1 Architecture (Legacy)]$]), which had no cryptographic signing capabilities. Migration from v1 to v2 included hash-chain reconstruction, and according to developer comments on [$[DPLAT-029]$], "Migration script tested with 500K legacy entries - all verified."

### Audit Log Retention Period

The retention configuration is as follows:
- **Default retention**: 2,555 days (approximately 7 years), as configured via the `AUDIT_RETENTION_DAYS` environment variable in the audit-log-service (per [$[audit-log-service — README]$]) and the `COMPLIANCE_RETENTION_DAYS` variable in the compliance-vault service (per [$[compliance-vault — README]$]).
- **Hot storage**: 12 months in PostgreSQL (per [$[ADR-007 — Storage Backend for Audit Log]$]), then archived.
- **Archival to cold storage**: After 90 days, logs are automatically moved to S3 Glacier (per [$[DPLAT-036]$]), with a maximum retrieval latency of 4 hours for archived records.
- **Per-tenant customization**: Workspace admins can configure custom retention periods per tenant, with a minimum of 30 days and maximum of 365 days (per [$[DPLAT-036]$]).

Note: The legacy v1 architecture (per [$[Audit Log v1 Architecture (Legacy)]$]) stated "indefinite" retention with no automatic deletion, but this has been superseded by the v2 architecture.

### How to Check for Log Gaps

To detect gaps in the audit log, you can use the following approaches:

1. **Hash chain verification**: The cryptographic hash chain inherently detects gaps. If a record is missing or tampered with, the hash chain will break, and subsequent entries will fail verification. This is the primary tamper-detection mechanism.

2. **Query-based gap detection**: Using the Audit Log Query DSL (documented in [$[Audit Log — Query Language Reference]$]), you can run time-range queries to identify missing intervals:
   - Query by timestamp ranges: `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`
   - Use aggregations to detect unusual drops in event counts: `AGGREGATE: count BY event_type`
   - Filter by specific event types to ensure expected events are present

3. **Retention policy awareness**: Queries for data older than the tenant's configured retention policy will return empty results (per [$[Audit Log — Query Language Reference]$]), so ensure you're querying within the retention window.

4. **Archival retrieval**: For logs older than 90 days that have been archived to S3 Glacier, retrieval may take up to 4 hours (per [$[DPLAT-036]$]). Gaps in archived data should be investigated through the daily retention summary report, which shows "count of logs archived, storage savings, and any failed archival operations."

The system maintains 99.95% availability for integrity verification read operations (per [$[DPLAT-REQ-09]$]), ensuring reliable gap detection.

**Sources:**
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Audit Log Retention

`⚠ conflict`

### How to Verify Log Integrity

Audit log integrity is maintained through **cryptographic hash-chaining**, as specified in [DPLAT-REQ-09]. Every audit record is cryptographically linked to its predecessor using SHA-256 (or stronger) hash functions, creating an immutable chain. This means:

- Each new audit log entry includes the hash of the previous entry, forming a tamper-evident sequence.
- Hash keys are stored in an HSM with FIPS 140-2 Level 3 certification, ensuring the chain cannot be retroactively altered without detection.
- Integrity verification can be performed by recomputing the hash chain across any range of records and comparing it to the stored chain. Any mismatch indicates tampering.
- The system supports verification at scale — up to 100 million historical records per workspace — with linear scaling (per [DPLAT-REQ-09]).

To verify integrity in practice, compliance officers can:
1. Query the audit log for a specific time range using the DSL (e.g., `timestamp:[NOW-90d TO NOW]`).
2. Request a hash-chain validation report through the Compliance Vault API or UI.
3. Compare the computed chain against the stored chain for any discrepancies.

### Audit Log Retention Period

The retention period for audit logs is **2555 days (approximately 7 years)** by default, as configured in both the [audit-log-service] (`AUDIT_RETENTION_DAYS=2555`) and [compliance-vault] (`COMPLIANCE_RETENTION_DAYS=2555`). However, there are multiple retention layers:

- **Hot storage (Postgres)**: 12 months of active retention, per [ADR-007]. After 12 months, logs are archived.
- **Cold storage (S3 Glacier)**: After 90 days, logs are automatically archived to S3 Glacier for cost-effective long-term storage, as implemented in [DPLAT-036]. Archived logs remain queryable with a maximum retrieval latency of 4 hours.
- **Per-tenant customization**: Workspace admins can configure custom retention periods per tenant, with a minimum of 30 days and maximum of 365 days (per [DPLAT-036]).
- **PII-tagged data**: A separate 30-day default retention applies specifically to PII-tagged data, after which it is anonymized or deleted (per the PII Auto-Tagging Policy).

Note: There is a known discrepancy — [DPLAT-DEF-04] reports that cached connector data defaults to 90 days instead of the documented 30 days. This bug is currently open and under investigation.

### How to Check for Log Gaps

To detect gaps in the audit log, use the hash-chain integrity mechanism combined with time-range queries:

1. **Hash-chain continuity check**: Since each record references the previous record's hash, any missing record will break the chain. The system can automatically detect gaps by verifying that consecutive records in the chain are properly linked.
2. **Time-range gap analysis**: Query the audit log using the DSL with time-range filters (e.g., `timestamp:[NOW-90d TO NOW]`). If the system returns fewer events than expected for a given period, or if there are time intervals with no events where activity is expected, this may indicate a gap.
3. **Retention boundary checks**: Queries older than the tenant's configured retention policy return empty results (per the Query Language Reference). This is expected behavior, not a gap — but compliance officers should verify that archival jobs ran successfully by checking the daily retention summary report (generated per [DPLAT-036]).
4. **Export validation**: When exporting audit logs via pre-signed URLs (24-hour expiry per [DPLAT-038]), the export includes cryptographic hash validation. Any gap in the exported chain will be flagged during verification.

For proactive monitoring, the system generates a daily retention summary report showing the count of logs archived, storage savings, and any failed archival operations (per [DPLAT-036]). Failed archival jobs could indicate potential gaps in the historical record.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)

## Retention Period

To verify audit log integrity in the context of retention, you need to understand the system's retention policies and how they interact with the cryptographic hash-chaining mechanism.

### Audit Log Retention Period

The system has a multi-tiered retention strategy:

1. **Hot Storage (Postgres)**: Audit logs are stored in Postgres with a default retention of **2555 days** (approximately 7 years), as configured by the `AUDIT_RETENTION_DAYS` environment variable in the [$[audit-log-service]$] and `COMPLIANCE_RETENTION_DAYS` in the [$[compliance-vault]$].

2. **Archival to Cold Storage**: Per [$[DPLAT-036]$], audit logs older than **90 days** are automatically archived to **S3 Glacier** storage. This is a cost-optimization measure that maintains compliance while reducing storage expenses.

3. **Per-Tenant Customization**: Workspace admins can configure custom retention periods per tenant, with a minimum of **30 days** and a maximum of **365 days** (per [$[DPLAT-036]$] acceptance criteria). The platform-wide default for PII-tagged data is **30 days** before automatic anonymization or deletion, as stated in the [$[PII Auto-Tagging — Policy and Behavior]$] document.

### How to Verify Log Integrity with Retention

The integrity verification mechanism is defined in [$[DPLAT-REQ-09]$]: every audit log record is **hash-chained** using SHA-256, with hash keys stored in an HSM (FIPS 140-2 Level 3 certified). This creates a cryptographic chain where each record's hash depends on the previous record, making tampering detectable.

To verify integrity across retention periods:

1. **For active records (under 90 days)**: Query the audit log via the DSL endpoint (`/api/v1/compliance/audit-query`) and validate the hash chain. The system supports verification for up to **100 million historical records** with linear scalability.

2. **For archived records (90+ days)**: Archived logs in S3 Glacier remain queryable via the Audit Log Export feature, with a maximum retrieval latency of **4 hours** (per [$[DPLAT-036]$]). After retrieval, you can validate the hash chain using the same cryptographic verification process.

3. **For exported records**: When exporting audit logs, the system generates an encrypted archive with a signed manifest containing SHA-256 hashes and RSA-2048 digital signatures (per [$[DPLAT-014]$]). The "Verify Export" button validates manifest signature and archive integrity without decryption.

### Checking for Log Gaps

To check for gaps in the audit log:

- Use the **time-range syntax** in the query DSL (e.g., `timestamp:[NOW-30d TO NOW]`) to identify missing time periods.
- The system generates a **daily retention summary report** showing the count of logs archived, storage savings, and any failed archival operations (per [$[DPLAT-036]$]).
- The hash chain itself provides gap detection: if a record's hash doesn't match the expected chain value, it indicates either tampering or a missing record.

**Key takeaway**: The retention period is 2555 days (7 years) by default, with hot storage in Postgres for the first 90 days and S3 Glacier archival thereafter. Integrity is maintained through SHA-256 hash chaining across all storage tiers, and gaps can be detected via the hash chain or daily retention reports.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)

## Storage Limits

### How to Verify Log Integrity

To verify audit log integrity within the context of storage limits, you rely on the **hash-chained architecture** implemented in the audit log v2 system. Per [$[DPLAT-029]$], each audit log entry includes a cryptographic hash of the previous entry, creating an unbroken chain that prevents undetectable tampering. Additionally, each entry contains a digital signature verifiable by compliance officers.

The verification process works as follows:
1. **Hash-chain validation**: You can traverse the log entries sequentially and verify that each entry's hash matches the hash stored in the subsequent entry. This detects any gaps or modifications.
2. **Digital signature verification**: Each entry's digital signature can be independently verified using the platform's public key, confirming the entry was created by the authorized system.
3. **Export verification**: When exporting logs (via [$[DPLAT-014]$]), the system generates an encrypted archive with a signed manifest containing SHA-256 hashes of the CSV data. A "Verify Export" button allows you to validate the manifest signature and confirm archive integrity without decryption.

### Audit Log Retention Period

The audit log retention period is **2555 days (approximately 7 years)** for hot storage, as configured by the `AUDIT_RETENTION_DAYS` environment variable in the [$[audit-log-service]$] and the `COMPLIANCE_RETENTION_DAYS` variable in the [$[compliance-vault]$] service. However, per [$[DPLAT-036]$] and [$[DPLAT-029]$], logs older than **90 days** are automatically archived to **S3 Glacier** cold storage. The archival process:
- Moves logs to S3 Glacier Deep Archive after 90 days (based on [$[DPLAT-036]$] testing)
- Archived logs remain queryable with a maximum retrieval latency of 4 hours
- Workspace admins can configure custom retention periods per tenant, with a minimum of 30 days and maximum of 365 days (per [$[DPLAT-036]$])

### How to Check for Log Gaps

To check for log gaps specifically related to storage limits:

1. **Hash-chain verification**: The hash-chaining mechanism inherently detects gaps. If a log entry is missing or deleted, the hash chain will break, and the subsequent entry's "previous hash" will not match the missing entry's hash. This is the primary method for gap detection.

2. **Export integrity checks**: When exporting logs, the signed manifest includes a cryptographic hash of the entire dataset. Comparing the hash of your exported data against the manifest hash will reveal if any records were omitted during export.

3. **Retention summary reports**: Per [$[DPLAT-036]$], a daily retention summary report is generated showing the count of logs archived, storage savings, and any failed archival operations. Failed archival operations could indicate gaps in the archived data.

4. **Query limitations**: The [$[Audit Log — Query Language Reference]$] notes that queries older than the tenant retention policy return empty results. If you query a date range and receive fewer results than expected, this could indicate that logs have been archived or purged according to the retention policy.

**Important note on storage limits**: The system uses Postgres for v2 audit log storage (per [$[ADR-007]$]), with a maximum of 100,000 events per query. If you need to verify integrity across a larger dataset, you must use the export functionality or query in smaller batches. The archival to S3 Glacier after 90 days means that logs older than 90 days are not in the primary database but are still accessible via the export feature with up to 4 hours retrieval latency.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)

## Archival Policy

`⚠ stale`

### How to Verify Log Integrity

The audit log system implements **hash-chained entries** for tamper detection, as specified in [$[DPLAT-029]$]. Each audit log entry includes a cryptographic hash of the previous entry, creating an unbroken chain that makes undetectable tampering impossible. This is the primary mechanism for verifying that archived logs have not been altered.

When you export audit logs for archival review, the system generates an **encrypted archive with a signed manifest** (per [$[DPLAT-014]$]). The manifest includes:
- A SHA-256 cryptographic hash of the audit log CSV
- The export timestamp and tenant identifier
- An RSA-2048 digital signature verifiable via the platform's public key

After export completion, a **"Verify Export" button** allows you to validate the manifest signature and confirm archive integrity without decryption. This ensures that archived logs remain authentic and unmodified during storage.

### Audit Log Retention Period

The retention policy for audit logs is **90 days** for hot storage, after which logs are automatically archived to **S3 Glacier** cold storage (per [$[DPLAT-036]$]). The system configuration shows `AUDIT_RETENTION_DAYS` set to **2555** (7 years) in the audit-log-service, but the archival lifecycle policy triggers at the **90-day threshold** for cost optimization. Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of **4 hours**.

Custom retention periods can be configured per tenant, with a minimum of **30 days** and maximum of **365 days** (per [$[DPLAT-036]$] acceptance criteria).

### How to Check for Log Gaps

To detect gaps in the audit log, you can use the **hash-chain verification** feature. Since each entry contains the hash of the previous entry, any missing or altered entry breaks the chain. The system's migration script for v2 architecture (tested with 500K legacy entries) ensures continuity.

For practical gap checking:
1. **Query the audit log** using the DSL (per [$[Audit Log — Query Language Reference]$]) with time-range filters to identify missing timestamps
2. **Use the "Verify Export" tool** on exported archives to confirm no entries were dropped during archival
3. **Review the daily retention summary report** (generated per [$[DPLAT-036]$]) which shows the count of logs archived and any failed archival operations

If you suspect gaps, compare the hash-chain continuity across consecutive exports or query the hot storage for the period before archival to ensure all entries were successfully transitioned to S3 Glacier.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)

## Compliance Mapping

### How to Verify Log Integrity

The audit log system implements **cryptographic hash chaining** to ensure tamper detection, as specified in [$[DPLAT-REQ-09]$]. Every audit record is cryptographically linked using **SHA-256** hash chains, with hash keys stored in an HSM (Hardware Security Module) certified to **FIPS 140-2 Level 3**. This means each record contains the hash of the previous record, creating an unbroken chain — if any record is modified, all subsequent hashes become invalid.

For compliance mapping purposes, integrity verification works as follows:

1. **Hash chain computation** occurs at write time, adding no more than **50ms overhead** per entry (per [$[DPLAT-REQ-09]$])
2. The system supports hash-chaining for up to **10,000 entries per second per tenant**
3. Verification scales linearly, supporting workspaces with up to **100 million historical records**
4. For exported audit logs, integrity is further protected by **AES-256-GCM encryption** with an **RSA-2048 signed manifest** (per [$[DPLAT-014]$]), allowing compliance officers to validate archive integrity without decryption via a "Verify Export" button

The storage backend (Postgres, per [$[ADR-007]$]) provides **native ACID transactions**, ensuring audit events are never lost or duplicated — a critical requirement for compliance integrity.

### Audit Log Retention Period

The retention configuration is multi-layered:

| Layer | Duration | Source |
|-------|----------|--------|
| **Default hot retention** | **90 days** | Per [$[DPLAT-036]$], logs older than 90 days are archived to S3 Glacier |
| **Total retention** | **2,555 days (~7 years)** | Configured via `AUDIT_RETENTION_DAYS` in [$[audit-log-service]$] and `COMPLIANCE_RETENTION_DAYS` in [$[compliance-vault]$] |
| **Per-tenant override** | **30–365 days** | Configurable by workspace admins (per [$[DPLAT-036]$] acceptance criteria) |
| **PII-tagged data** | **30 days** | Default retention for PII-tagged data before anonymization/deletion (per [$[PII Auto-Tagging Policy]$]) |

After 90 days, logs move to **S3 Glacier Deep Archive** for cost-optimized long-term storage, with a maximum retrieval latency of **4 hours** for archived records (per [$[DPLAT-036]$]).

### How to Check for Log Gaps

For compliance mapping, log gap detection relies on the **hash chain integrity mechanism**:

1. **Hash chain validation**: Since every record is linked to its predecessor via SHA-256, any missing record breaks the chain. Running a verification scan across the entire chain will immediately identify gaps where hashes don't match or sequences are interrupted.

2. **Query-based gap detection**: Using the [$[Audit Log Query Language Reference]$], compliance officers can run time-range queries (e.g., `timestamp:[NOW-30d TO NOW]`) and compare expected event counts against actual records. The aggregation functions (`AGGREGATE: count BY event_type`) help identify periods with unexpectedly low activity.

3. **Export verification**: When exporting logs via [$[DPLAT-014]$], the signed manifest includes a SHA-256 hash of the entire CSV. If records are missing from the export, the hash won't match, alerting the compliance officer to potential gaps.

4. **Availability guarantee**: The integrity verification system maintains **99.95% availability** during read operations (per [$[DPLAT-REQ-09]$]), ensuring gap detection can be performed reliably.

**Key compliance mapping takeaway**: The hash chain provides **cryptographic proof of continuity** — if the chain validates from the earliest record to the latest, there are no gaps. Any break in the chain indicates either tampering or data loss, triggering a compliance incident investigation.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)

## Security & Tamper Detection

`⚠ conflict`

### How to Verify Log Integrity

Audit log integrity is maintained through **cryptographic hash chaining**, where every audit record is cryptographically linked to the previous one using SHA-256 (or stronger) hashing, as specified in [$[DPLAT-REQ-09]$]. This creates an immutable chain where tampering with any record breaks the chain and becomes immediately detectable.

To verify integrity, you can:

1. **Use the Compliance Vault's verification tools** — The system provides a "Verify Export" button (per [$[DPLAT-014]$]) that validates the manifest signature and confirms archive integrity without requiring decryption. This allows compliance officers to cryptographically prove that exported audit logs have not been altered.

2. **Validate hash chains programmatically** — Each audit log record contains a hash of the previous record. By recomputing the hash chain from the first record to the last, you can detect any break or inconsistency. The system supports this verification for workspaces with up to **100 million historical records** (per [$[DPLAT-REQ-09]$]).

3. **Check exported archives** — When exporting audit logs, the system generates an encrypted archive (AES-256-GCM) containing a `manifest.json` file with the SHA-256 hash of the audit log CSV, export timestamp, tenant identifier, and an RSA-2048 digital signature. This signed manifest provides non-repudiation and allows external auditors to verify authenticity using the platform's public key (per [$[DPLAT-014]$]).

### Audit Log Retention Period

The retention configuration varies by context:

- **Platform-wide default**: The PII Auto-Tagging policy specifies a **30-day** retention for PII-tagged data (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Audit log service default**: The `AUDIT_RETENTION_DAYS` environment variable defaults to **2555 days** (~7 years) (per [$[audit-log-service README]$]).
- **Compliance Vault default**: The `COMPLIANCE_RETENTION_DAYS` variable also defaults to **2555 days** (per [$[compliance-vault README]$]).
- **Archival policy**: Audit logs are automatically archived to **S3 Glacier after 90 days** (per [$[DPLAT-036]$]). Archived logs remain queryable with a maximum retrieval latency of 4 hours.
- **Per-tenant overrides**: Workspace admins can configure custom retention periods between **30 and 365 days** (per [$[DPLAT-036]$]).

Note: The Engineering Offsite notes mention a 90-day retention period under review, but the current implementation uses 2555 days as the default.

### How to Check for Log Gaps

To detect gaps in the audit log:

1. **Verify hash chain continuity** — Since every record is hash-chained, a missing record will break the chain. The system's integrity verification will flag any discontinuity.

2. **Use the Audit Log Query DSL** — Query for specific time ranges using the `timestamp` field with absolute or relative ranges (e.g., `timestamp:[NOW-30d TO NOW]`). Compare expected event counts against actual results. The query language supports aggregations like `AGGREGATE: count BY event_type` to summarize activity (per [$[Audit Log — Query Language Reference]$]).

3. **Monitor archival operations** — The daily retention summary report (per [$[DPLAT-036]$]) shows the count of logs archived and any failed archival operations, which can indicate gaps in the log sequence.

4. **Check for missing tenant context** — The system requires that every audit log entry includes a tenant identifier (per [$[Engineering Offsite — Berlin 2026]$]). Missing tenant context could indicate gaps in logging coverage.

**Security-critical note**: The hash chain computation adds no more than **50ms overhead per entry** and supports up to **10,000 entries per second per tenant** (per [$[DPLAT-REQ-09]$]). Hash keys are stored in an HSM with **FIPS 140-2 Level 3 certification**, ensuring the cryptographic foundation of the integrity verification system is secure.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)

## Gap Analysis

### How to Verify Log Integrity

The system implements **cryptographic hash chaining** to ensure audit log integrity and detect tampering. According to [JIRA] [$[DPLAT-REQ-09]$], every audit log record is cryptographically linked using hash chains with the following specifications:

- **Hash algorithm**: SHA-256 (or stronger), with hash keys stored in an HSM certified to FIPS 140-2 Level 3
- **Performance**: Hash chain computation adds no more than 50ms overhead per entry, supporting up to 10,000 entries per second per tenant
- **Availability**: Integrity verification maintains 99.95% availability during read operations
- **Scalability**: Verification scales linearly for workspaces with up to 100 million historical records

Additionally, for exported audit logs, integrity can be verified through the **signed manifest** feature described in [JIRA] [$[DPLAT-014]$]. When exporting, the system generates an encrypted archive containing:
- The audit log CSV
- A `manifest.json` with SHA-256 hash of the CSV, export timestamp, tenant ID, and an RSA-2048 digital signature
- A "Verify Export" button allows compliance officers to validate the manifest signature and confirm archive integrity without decryption

### Audit Log Retention Period

There are **two distinct retention periods** in the system:

1. **Hot storage (Postgres)**: 12 months per [CONFLUENCE] [$[ADR-007]$], though the actual configured retention is **2555 days (7 years)** as shown in the [$[audit-log-service]$] configuration (`AUDIT_RETENTION_DAYS=2555`) and the [$[compliance-vault]$] configuration (`COMPLIANCE_RETENTION_DAYS=2555`).

2. **Cold storage (S3 Glacier)**: After **90 days**, audit logs are automatically archived to S3 Glacier per [JIRA] [$[DPLAT-036]$]. Archived logs remain queryable with a maximum retrieval latency of 4 hours. Workspace admins can configure custom retention per tenant (minimum 30 days, maximum 365 days).

Note: The [$[Engineering Offsite]$] notes from January 2026 mention a 90-day retention period under review, but the current implementation uses the 2555-day (7-year) configuration.

### How to Check for Log Gaps

The system provides several mechanisms to detect gaps or anomalies in audit logs:

1. **Hash chain verification**: Because records are cryptographically linked, any missing or tampered record will break the chain. The system can detect gaps by verifying the continuity of hash links across the entire chain.

2. **Query DSL**: The [$[Audit Log Query Language Reference]$] provides tools to identify gaps:
   - Use time-range queries to check for missing periods: `timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]`
   - Aggregate by time intervals to spot missing data: `AGGREGATE: count BY event_type`
   - Filter by status to find failed events that might indicate gaps: `status!=failed`

3. **Retention summary reports**: Per [JIRA] [$[DPLAT-036]$], a daily retention summary report is generated showing the count of logs archived, storage savings, and **any failed archival operations** — which could indicate gaps in the log chain.

4. **Export verification**: When exporting logs, the signed manifest includes a cryptographic hash of the entire dataset. Any gap between the expected and actual hash indicates missing or altered records.

### Key Gap Analysis Findings

The primary gap in the current implementation is that **hash chaining is specified as a requirement** ([$[DPLAT-REQ-09]$]) but the actual implementation status is not fully confirmed across all storage tiers. Specifically:
- Hash chaining is required for hot storage (Postgres) per the requirement
- It is unclear whether hash chains are maintained when logs are archived to S3 Glacier after 90 days
- The 4-hour retrieval latency for archived logs means gap detection for cold storage data is not real-time

For a complete gap analysis, compliance officers should verify that hash chain verification works across both hot and cold storage tiers, and that the daily retention reports include gap detection alerts for any missing records in the chain.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)

## Unauthorized Access Alerts

`⚠ stale`

### How to Verify Log Integrity

The audit log system implements **hash-chained integrity verification** to detect tampering, including unauthorized access events. According to [$[DPLAT-REQ-09]$], every audit record is cryptographically linked using SHA-256 hash chains, where each entry includes a cryptographic hash of the previous entry. This creates an immutable chain that makes retroactive tampering detectable.

To verify integrity for unauthorized access alerts:

1. **Hash Chain Verification**: The system computes SHA-256 hashes for each audit entry and links them sequentially. A compliance officer can verify the chain by recomputing hashes from a known-good starting point and comparing them against stored values. Per [$[DPLAT-029]$], the v2 architecture implements this with hash-chained entries, and migration from v1 included reconstruction of hash chains for legacy data.

2. **Digital Signature Validation**: Each audit log entry includes a digital signature that can be verified by the compliance officer. The hash keys are stored in an HSM with FIPS 140-2 Level 3 certification (per [$[DPLAT-REQ-09]$]).

3. **Export Verification**: When exporting audit logs, the system generates a signed manifest containing SHA-256 hashes of the exported data, signed with RSA-2048. The "Verify Export" feature allows compliance officers to validate manifest signatures and confirm archive integrity without decryption (per [$[DPLAT-014]$]).

4. **Query-Based Verification**: Using the Audit Log Query DSL (per [$[DPLAT/13-audit-log-query-reference]$]), you can filter for unauthorized access events by querying `event_type=auth.login AND status=failed` or similar patterns, then verify the hash chain for those specific entries.

### Audit Log Retention Period

The retention configuration is as follows:

- **Hot storage**: 90 days in PostgreSQL (per [$[DPLAT-036]$] and [$[DPLAT-029]$])
- **Cold storage**: After 90 days, logs are automatically archived to S3 Glacier (per [$[DPLAT-036]$])
- **Total retention**: The default retention period is **2555 days** (7 years), as configured via the `AUDIT_RETENTION_DAYS` environment variable in the audit-log-service (per [$[audit-log-service README]$]) and `COMPLIANCE_RETENTION_DAYS` in the compliance-vault service (per [$[compliance-vault README]$])
- **Customizable**: Workspace admins can configure custom retention periods per tenant, with a minimum of 30 days and maximum of 365 days (per [$[DPLAT-036]$])

Note: The v1 architecture (legacy) retained events indefinitely with no automatic deletion, but this has been superseded by the v2 architecture with defined retention policies.

### How to Check for Log Gaps

To detect gaps in the audit log, particularly for unauthorized access alerts:

1. **Hash Chain Continuity**: The hash chain itself provides gap detection. If a record is missing or deleted, the hash chain will break because each entry's hash depends on the previous entry. A compliance officer can run a hash chain verification script that traverses the chain and reports any discontinuity.

2. **Sequence Number Analysis**: The `audit_events` table uses a `BIGSERIAL` primary key (per [$[Audit Log v1 Architecture]$]). Gaps in the auto-incrementing sequence can indicate missing records. Query for missing IDs using:
   ```
   SELECT id FROM audit_events ORDER BY id
   ```
   and look for jumps in the sequence.

3. **Timestamp Range Queries**: Use the Audit Log Query DSL to check for time periods with no events where you expect activity. For unauthorized access alerts, query:
   ```
   event_type=auth.login AND status=failed AND timestamp:[NOW-7d TO NOW]
   ```
   If expected events are missing during known incident windows, this may indicate a gap.

4. **Archival Verification**: For archived logs (older than 90 days), the system generates a daily retention summary report showing the count of logs archived and any failed archival operations (per [$[DPLAT-036]$]). Review these reports to identify gaps in archival coverage.

5. **Export Integrity Checks**: When exporting audit logs, the signed manifest includes cryptographic hashes. Comparing the hash of exported data against the manifest reveals if any records were omitted or altered during export (per [$[DPLAT-014]$]).

**Key limitation**: The system supports hash chain verification for up to 100 million historical audit records per workspace, with 99.95% availability during read operations (per [$[DPLAT-REQ-09]$]).

**Sources:**
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)

## Immutable Logs

`⚠ conflict` `⚠ stale`

### How to Verify Log Integrity

The audit log system implements **cryptographic hash chaining** to ensure tamper detection, as specified in requirement [$[DPLAT-REQ-09]$]. Every audit log record is cryptographically linked to its predecessor using **SHA-256** (or stronger) hash functions, creating an immutable chain where any modification to a historical record would break the chain and be immediately detectable.

The hash chain computation adds no more than **50ms overhead per entry** and supports up to **10,000 entries per second per tenant**. Hash keys are stored in an **HSM with FIPS 140-2 Level 3 certification** for maximum security.

To verify integrity:
- **For exported logs**: Use the **"Verify Export"** button available after export completion (per [$[DPLAT-014]$]). This validates the **RSA-2048 digital signature** in the manifest.json file against the SHA-256 hash of the audit log CSV, confirming archive integrity without requiring decryption.
- **For live logs**: The system maintains hash chain verification that scales linearly, supporting workspaces with up to **100 million historical audit records** (per [$[DPLAT-REQ-09]$]).
- **For archived logs**: Archived logs in S3 Glacier (after 90 days, per [$[DPLAT-036]$]) retain their hash chain integrity and can be verified upon retrieval.

### Audit Log Retention Period

The retention configuration is **multi-tiered**:

| Tier | Duration | Storage | Source |
|------|----------|---------|--------|
| **Hot retention** | 90 days | PostgreSQL (primary) | [$[DPLAT-036]$] |
| **Cold archive** | After 90 days | S3 Glacier | [$[DPLAT-036]$] |
| **Maximum configurable** | 2555 days (7 years) | Configurable via `AUDIT_RETENTION_DAYS` | [$[audit-log-service]$] README |
| **Per-tenant override** | 30–365 days | Configurable by workspace admin | [$[DPLAT-036]$] |

Note: The legacy v1 architecture (per [$[Audit Log v1 Architecture (Legacy)]$]) retained events indefinitely, but the current v2 implementation uses the retention policies above. The ADR-007 decision (per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$]) specifies **12 months hot retention** before archival, though the implemented behavior in [$[DPLAT-036]$] uses 90 days.

### How to Check for Log Gaps

To detect gaps in the immutable log chain:

1. **Hash chain verification**: Since every record is hash-chained, any missing record would break the cryptographic link between its predecessor and successor. The system automatically detects such breaks during integrity verification.

2. **Query-based gap detection**: Use the **Audit Log Query DSL** (per [$[Audit Log — Query Language Reference]$]) with time-range filters to identify missing timestamps:
   ```
   timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]
   ```
   Compare expected event counts against actual results for each time interval.

3. **Export verification**: When exporting logs via pre-signed URLs (per [$[DPLAT-038]$]), the signed manifest includes the record count and hash. Discrepancies between expected and actual record counts indicate potential gaps.

4. **Retention summary reports**: Daily reports generated per [$[DPLAT-036]$] show the count of logs archived and any **failed archival operations**, which could indicate gaps in the archive tier.

The system maintains **99.95% availability** for integrity verification read operations (per [$[DPLAT-REQ-09]$]), ensuring gap detection is consistently available.

**Sources:**
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)

## Audit Logs

# Audit Log Integrity Verification

## How to Verify Log Integrity

According to [JIRA] DPLAT-REQ-09, every audit log record is **hash-chained** for tamper detection. This means each record is cryptographically linked to the previous one using SHA-256 (or stronger) hashing, creating an immutable chain. To verify integrity:

1. **Recompute the hash chain**: Starting from the first record, recompute the hash of each subsequent record and compare it against the stored hash. Any mismatch indicates tampering.
2. **HSM-backed keys**: Hash keys are stored in a Hardware Security Module with FIPS 140-2 Level 3 certification, ensuring the chain cannot be forged (per [JIRA] DPLAT-REQ-09).
3. **Linear scalability**: Verification scales linearly, supporting up to 100 million historical records per workspace (per [JIRA] DPLAT-REQ-09).
4. **Performance guarantee**: Hash chain computation adds no more than 50ms overhead per entry, and the system supports up to 10,000 hash-chained entries per second per tenant (per [JIRA] DPLAT-REQ-09).

The system uses **Postgres** as the storage backend (per [CONFLUENCE] ADR-007), which provides native ACID transactions — ensuring audit events are never lost or duplicated, which is foundational to integrity.

## Audit Log Retention Period

There are **two different retention configurations** in the system:

| Source | Retention Period | Details |
|--------|-----------------|---------|
| [GITHUB] audit-log-service README | **2555 days** (~7 years) | Default `AUDIT_RETENTION_DAYS` environment variable |
| [GITHUB] compliance-vault README | **2555 days** (~7 years) | Default `COMPLIANCE_RETENTION_DAYS` environment variable |
| [JIRA] DPLAT-036 | **90 days hot** → then archived to S3 Glacier | After 90 days, logs move to cold storage automatically |
| [CONFLUENCE] Engineering Offsite Berlin 2026 | **90 days** (under review) | Current retention, being evaluated for compliance |

**How it works**: Per [JIRA] DPLAT-036, audit logs older than 90 days are automatically identified and moved to S3 Glacier Deep Archive storage. The workspace admin can configure custom retention periods per tenant (minimum 30 days, maximum 365 days). Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of 4 hours.

The 2555-day (7-year) default in the service configuration likely represents the maximum retention window before deletion, while the 90-day threshold triggers the transition to cold storage.

## How to Check for Log Gaps

To detect gaps or missing audit log entries:

1. **Query the hash chain**: Since records are hash-chained (per [JIRA] DPLAT-REQ-09), any missing record will break the chain. Recomputing the chain and identifying discontinuities reveals gaps.

2. **Use the Audit Log Query DSL** (per [CONFLUENCE] Audit Log — Query Language Reference):
   - Query by time range: `timestamp:[NOW-30d TO NOW]` to see if expected events are present
   - Filter by event type: `event_type IN (data_access, data_modify, data_delete)` to check for missing categories
   - Use aggregations: `AGGREGATE: count BY event_type` to spot unusual drops in event volume

3. **Check for gaps in chronological sequence**: The `audit_events` table (per [CONFLUENCE] Audit Log v1 Architecture) uses an auto-incrementing `id` (BIGSERIAL) and `timestamp` (TIMESTAMPTZ). Querying for missing IDs or unexpected time gaps between consecutive records can reveal gaps.

4. **Monitor archival operations**: Per [JIRA] DPLAT-036, a daily retention summary report shows the count of logs archived and any failed archival operations — failures could indicate data loss.

5. **Performance indicators**: If queries on 6-month data exceed 5 seconds (per [CONFLUENCE] ADR-007), it may indicate indexing issues or data gaps that need investigation.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)

## Compliance Reporting

### How to Verify Log Integrity

For compliance reporting purposes, audit log integrity is ensured through **cryptographic hash chaining**. According to [JIRA] DPLAT-REQ-09, every audit record is cryptographically linked using SHA-256 (or stronger) hash functions, with hash keys stored in an HSM certified to FIPS 140-2 Level 3. This creates an immutable chain where tampering with any record breaks the hash linkage, making unauthorized modifications detectable.

The hash chain computation adds no more than **50ms overhead per entry** and supports up to **10,000 entries per second per tenant**. Integrity verification scales linearly, supporting workspaces with up to **100 million historical records**. Compliance officers can validate the chain by recomputing hashes across records and checking for breaks — any gap or mismatch indicates tampering.

Per [CONFLUENCE] ADR-007, the system uses **PostgreSQL** as the storage backend for v2, which provides native ACID transactions — ensuring audit events are never lost or duplicated. This transactional integrity is foundational for compliance reporting, as it guarantees that the hash chain is built on a complete, consistent record set.

### Audit Log Retention Period

The retention configuration is multi-layered:

- **Hot storage**: Audit logs are retained in PostgreSQL for **90 days** (per [JIRA] DPLAT-036, logs older than 90 days are automatically archived to S3 Glacier).
- **Cold storage**: Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of **4 hours**.
- **Platform default**: The `AUDIT_RETENTION_DAYS` environment variable is set to **2555 days** (approximately 7 years) — this is the maximum retention window before automatic deletion (per [GITHUB] audit-log-service README and [GITHUB] compliance-vault README).
- **Per-tenant overrides**: Workspace admins can configure custom retention periods between **30 and 365 days** (per [JIRA] DPLAT-036).

For compliance reporting, this means:
- Recent 90 days: immediate query access via PostgreSQL
- 90 days to 7 years: available via S3 Glacier with 4-hour retrieval latency
- Beyond 7 years: data is deleted per the `AUDIT_RETENTION_DAYS` setting

### How to Check for Log Gaps

To detect gaps in the audit log for compliance reporting:

1. **Hash chain validation**: The cryptographic hash chain inherently reveals gaps — if a record is missing or altered, the hash of the subsequent record will not match the expected value. This is the primary tamper-detection mechanism.

2. **Timestamp continuity checks**: Using the [CONFLUENCE] Audit Log Query Language Reference, compliance officers can query for timestamp gaps:
   ```
   event_type=* AND timestamp:[NOW-90d TO NOW]
   ```
   Then sort by timestamp and look for discontinuities. The system indexes on `timestamp` and `tenant_id` for efficient chronological scanning.

3. **Archival verification**: Per [JIRA] DPLAT-036, a **retention summary report** is generated daily showing the count of logs archived, storage savings, and any **failed archival operations**. Failed archival operations may indicate gaps in the cold storage layer.

4. **Export validation**: When exporting logs via pre-signed URLs (per [JIRA] DPLAT-038), the export includes cryptographic hash validation — zero data integrity issues are expected across all export operations (per [JIRA] DPLAT-EPIC-05 success metrics).

For compliance reporting specifically, the recommended approach is to run periodic hash chain verification across the full retention window, combined with daily archival status reports to ensure no data loss during the hot-to-cold transition at the 90-day mark.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)

## Verification Reports

`⚠ conflict`

### How to Verify Log Integrity

The audit log system implements **hash-chained integrity** to prevent undetected tampering. According to [$[DPLAT-REQ-09]$], every audit log record is cryptographically linked using SHA-256 hash chains, where each entry includes a cryptographic hash of the previous entry. This creates an immutable chain: if any record is modified, all subsequent hashes become invalid.

To verify integrity, compliance officers can use the **"Verify Export"** feature described in [$[DPLAT-014]$]. After generating an audit log export, a "Verify Export" button appears, allowing you to validate the manifest signature and confirm archive integrity without decryption. The export generates a `.zip` archive containing:
- The audit log CSV file
- A `manifest.json` file with the SHA-256 hash of the CSV, export timestamp, tenant identifier, and an RSA-2048 digital signature

You can verify the manifest signature using the platform's public key. Additionally, the hash chain itself can be validated by recomputing the chain from the first entry to the last—any mismatch indicates tampering.

### Audit Log Retention Period

The retention configuration is multi-layered:

- **Hot storage (Postgres)**: 12 months per [$[ADR-007]$], though the service configuration defaults to **2555 days (~7 years)** via the `AUDIT_RETENTION_DAYS` environment variable (per [$[audit-log-service README]$]).
- **Archival to cold storage**: After **90 days**, logs are automatically moved to S3 Glacier (per [$[DPLAT-036]$]). Archived logs remain queryable with a maximum retrieval latency of 4 hours.
- **Per-tenant overrides**: Workspace admins can configure custom retention periods between 30 and 365 days (per [$[DPLAT-036]$] acceptance criteria).

Note: There is a known discrepancy—the PII auto-tagging policy documents a 30-day default retention for cached PII data, but the actual system default is 90 days (see [$[DPLAT-DEF-04]$]).

### How to Check for Log Gaps

To detect gaps in the audit log, use the **hash chain verification** mechanism:

1. **Chain continuity check**: Since each entry contains the hash of the previous entry, any missing record will break the chain. The system can detect gaps by verifying that the hash chain is continuous from the first to the last record in a given time range.

2. **Query-based gap detection**: Use the Audit Log Query DSL (per [$[Audit Log — Query Language Reference]$]) to run time-range queries and look for unexpected gaps in event timestamps. For example:
   ```
   timestamp:[2026-03-01T00:00:00Z TO 2026-03-31T23:59:59Z]
   ```
   Then sort by timestamp and check for intervals exceeding expected event frequency.

3. **Export verification**: When exporting logs via [$[DPLAT-014]$], the signed manifest includes the SHA-256 hash of the entire CSV. If records were deleted or modified between export and verification, the hash will not match, indicating a gap or tampering.

4. **Archival integrity**: For archived logs (older than 90 days, stored in S3 Glacier per [$[DPLAT-036]$]), the hash chain is preserved during archival. When retrieving archived logs, the chain can be re-verified to ensure no gaps were introduced during the archival process.

The system supports hash chain verification for up to **100 million historical records** per workspace, with linear scalability (per [$[DPLAT-REQ-09]$]).

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)

## Compliance Documentation

### How to Verify Log Integrity

The audit log system implements **cryptographic hash chaining** to ensure tamper-evident records. According to [$[DPLAT-REQ-09]$], every audit log record is linked to the previous entry using SHA-256 hashing, with hash keys stored in a Hardware Security Module (HSM) certified at FIPS 140-2 Level 3. This creates an immutable chain where any modification to a historical record would break the hash linkage, making tampering immediately detectable.

To verify integrity, compliance officers can use the **"Verify Export"** feature described in [$[DPLAT-014]$]. When exporting audit logs, the system generates an encrypted archive (AES-256-GCM) containing:
- The audit log CSV file
- A `manifest.json` with the SHA-256 hash of the CSV, export timestamp, tenant identifier, and an RSA-2048 digital signature

The verification tool validates the manifest signature and confirms archive integrity **without requiring decryption**, allowing compliance officers to cryptographically prove that exported logs have not been altered since export.

### Audit Log Retention Period

The system has **two-tier retention**:

| Tier | Duration | Storage |
|------|----------|---------|
| Hot storage | 90 days | PostgreSQL (per ADR-007) |
| Cold archive | Up to 7 years (2555 days) | S3 Glacier |

Per [$[DPLAT-036]$], audit logs older than 90 days are automatically archived to S3 Glacier Deep Archive. The default retention is **2555 days** (7 years), as configured via `COMPLIANCE_RETENTION_DAYS` in the compliance-vault service and `AUDIT_RETENTION_DAYS` in the audit-log-service. Workspace admins can configure custom retention per tenant, with a minimum of 30 days and maximum of 365 days for the hot tier.

### How to Check for Log Gaps

To detect gaps in the audit log, compliance officers should:

1. **Query using the Audit Log DSL** (per [$[Audit Log — Query Language Reference]$]): Use time-range queries with `timestamp:[NOW-90d TO NOW]` and aggregate by date to identify missing intervals.

2. **Verify hash chain continuity**: Since every record is hash-chained, any missing sequence number or broken hash link indicates a gap. The system's hash chain verification scales linearly for up to 100 million records.

3. **Review the daily retention summary report**: Per [$[DPLAT-036]$], the system generates a daily report showing the count of logs archived, storage savings, and **any failed archival operations** — which could indicate gaps in the cold storage tier.

4. **Check export integrity**: When generating exports via the pre-signed URL mechanism (24-hour expiry per [$[DPLAT-038]$]), the signed manifest includes the record count. A mismatch between expected and actual record count signals a gap.

**Key compliance note**: The system uses PostgreSQL for hot storage specifically because ACID transactions ensure audit events are never lost or duplicated (per ADR-007). For archived logs in S3 Glacier, retrieval takes up to 4 hours, but the hash chain verification remains valid across both storage tiers.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-039] Audit Log — batch sign-off workflow for compliance officer](https://demo-jira.local/browse/DPLAT-039)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)

## Auditor Access

`⚠ stale`

### How to Verify Log Integrity

Audit log integrity is maintained through **cryptographic hash-chaining**, as specified in requirement [$[DPLAT-REQ-09]$]. Every audit log record includes a cryptographic hash of the previous entry, creating an immutable chain that prevents undetected tampering. This is implemented in the v2 architecture (per [$[DPLAT-029]$]), which replaced the legacy v1 single-table design.

To verify integrity as an auditor:

1. **Hash chain verification**: Each entry contains a SHA-256 (or stronger) hash linking it to the prior record. Compliance officers can verify the chain by recomputing hashes sequentially and confirming they match. Hash keys are stored in an HSM with FIPS 140-2 Level 3 certification.

2. **Digital signature validation**: Every audit log entry includes a digital signature that can be independently verified by the compliance officer (per [$[DPLAT-029]$] acceptance criteria).

3. **Query-based verification**: Using the Audit Log Query DSL (per [$[Audit Log — Query Language Reference]$]), auditors can run time-range queries and export results for offline chain validation. The system supports verification at scale — up to 100 million historical records with linear scaling (per [$[DPLAT-REQ-09]$]).

4. **Export with integrity**: When downloading audit logs via pre-signed URLs (24-hour expiry, per [$[DPLAT-038]$]), the exported files maintain the hash-chain structure, allowing external auditors to verify integrity independently.

### Audit Log Retention Period

The retention configuration is multi-tiered:

- **Hot storage (Postgres)**: 12 months per ADR-007, though the v1 architecture originally retained indefinitely. The v2 architecture (per [$[DPLAT-029]$]) implements automatic archival.
- **Archival to S3 Glacier**: After **90 days**, audit logs are automatically moved to S3 Glacier cold storage (per [$[DPLAT-036]$]). Archived logs remain queryable with a maximum retrieval latency of 4 hours.
- **Configuration defaults**: The audit-log-service defaults to **2555 days** (~7 years) retention via the `AUDIT_RETENTION_DAYS` environment variable (per [$[audit-log-service]$] README). The compliance-vault service also defaults to **2555 days** via `COMPLIANCE_RETENTION_DAYS`.
- **Per-tenant overrides**: Workspace admins can configure custom retention periods per tenant, with a minimum of 30 days and maximum of 365 days (per [$[DPLAT-036]$]).

### How to Check for Log Gaps

To detect gaps or missing audit records:

1. **Hash chain continuity**: The hash-chaining mechanism inherently detects gaps — if a record is missing or tampered with, the hash chain will break. The verification process will fail at the point of discontinuity.

2. **Timestamp sequence analysis**: Query the audit log using the DSL with chronological ordering (`timestamp:[START TO END]`) and check for unexpected time gaps between consecutive events. The system indexes on `timestamp` and `tenant_id` for efficient range queries.

3. **Export comparison**: Export audit logs for overlapping time ranges and compare record counts and hash chains. The pre-signed URL export feature (per [$[DPLAT-038]$]) supports CSV and JSON formats for offline analysis.

4. **Retention boundary checks**: When querying across the 90-day archival boundary, note that archived logs require up to 4 hours retrieval latency (per [$[DPLAT-036]$]). Queries older than the tenant's configured retention policy return empty results (per the Query Language Reference limitations).

5. **Integrity verification SLA**: The system maintains 99.95% availability for integrity verification read operations (per [$[DPLAT-REQ-09]$]), ensuring auditors can reliably check for gaps at any time.

**Sources:**
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Summary

### How to Verify Log Integrity

Audit log integrity is maintained through **cryptographic hash chaining**, where every audit record is cryptographically linked to the previous one using SHA-256 hashing (per [JIRA] [$[DPLAT-REQ-09]$]). This creates an immutable chain that makes tampering detectable — if any record is modified, the hash chain breaks.

To verify integrity:
- The system computes hash chains automatically for every audit log entry, with a maximum overhead of **50ms per entry** and support for up to **10,000 entries per second per tenant** (based on [JIRA] [$[DPLAT-REQ-09]$]).
- For exported audit logs, integrity can be verified using the **"Verify Export"** feature, which validates the RSA-2048 digital signature on the manifest file and confirms the SHA-256 hash of the CSV content without requiring decryption (per [JIRA] [$[DPLAT-014]$]).
- Hash keys are stored in an HSM with **FIPS 140-2 Level 3** certification, ensuring the cryptographic material itself is protected ([JIRA] [$[DPLAT-REQ-09]$]).

### Audit Log Retention Period

The retention configuration is multi-layered:

| Layer | Retention Period | Source |
|-------|-----------------|--------|
| **Platform default** | 2,555 days (~7 years) | [GITHUB] audit-log-service README (`AUDIT_RETENTION_DAYS=2555`) |
| **Hot storage** | 90 days in Postgres | [JIRA] [$[DPLAT-036]$] |
| **Cold storage** | After 90 days → archived to S3 Glacier | [JIRA] [$[DPLAT-036]$] |
| **PII-tagged data** | 30 days before anonymization/deletion | [CONFLUENCE] PII Auto-Tagging Policy |
| **Per-tenant override** | Configurable min 30 days, max 365 days | [JIRA] [$[DPLAT-036]$] |

Note: The [CONFLUENCE] Engineering Offsite notes mention a "90-day" retention under review, but the actual configured value in the service is **2,555 days** — the 90-day figure refers to the hot storage window before archival to S3 Glacier.

### How to Check for Log Gaps

The hash chain mechanism inherently detects gaps — if a record is missing from the sequence, the chain will fail verification at the point of discontinuity. Additionally:

- **Query completeness**: The audit log query DSL (per [CONFLUENCE] [$[Audit Log — Query Language Reference]$]) supports time-range filters (`timestamp:[NOW-30d TO NOW]`) and aggregation queries (`AGGREGATE: count BY event_type`) that can reveal unexpected gaps in event coverage.
- **Export validation**: When exporting logs, the signed manifest includes a complete record count and hash, enabling comparison against expected totals ([JIRA] [$[DPLAT-014]$]).
- **Retention summary reports**: A daily report is generated showing the count of logs archived and any failed archival operations, which can indicate gaps in the archival process ([JIRA] [$[DPLAT-036]$]).

**Key takeaway**: The hash chain provides the primary tamper-detection mechanism. If the chain is intact from the first to the last record, no gaps or modifications have occurred. For exported data, the "Verify Export" tool provides a quick integrity check without needing to decrypt the archive.

**Sources:**
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-09] Audit Log integrity — every record is hash-chained for tamper detection](https://demo-jira.local/browse/DPLAT-REQ-09)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-038] Audit Log — pre-signed URL for download (24h expiry)](https://demo-jira.local/browse/DPLAT-038)
- 📋 [[DPLAT-014] Audit Log Export — encrypted archive format with signed manifest](https://demo-jira.local/browse/DPLAT-014)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-REQ-08] Audit Log Export — full export of 90 days fits in 4 GB compressed CSV](https://demo-jira.local/browse/DPLAT-REQ-08)
