# 3.3  Retention policy and per-tenant overrides

> Managing data lifecycle based on PII tags.

## Policy Configuration

`⚠ conflict`

### Setting Retention for Tagged Data

To configure retention for PII-tagged data, you work through the **Compliance Vault UI** or the **tenant configuration API**. The platform applies a default retention period of **60 days** for all PII-tagged data in connector caches, as specified in [$[DPLAT-006]$]. This overrides the previously documented 30-day rule from the PII Auto-Tagging policy (per [$[CONFLUENCE]$] PII Auto-Tagging — Policy and Behavior).

**Important note:** There is a known discrepancy — the actual observed default for cached connector data is **90 days**, not 30 days as originally documented (see [$[DPLAT-DEF-04]$]). The 60-day default introduced in DPLAT-006 is intended to resolve this inconsistency.

### Per-Tenant Retention Override

Yes, you can override retention per tenant. Workspace admins can set a **custom retention period (1–365 days)** per tenant via the Compliance Vault UI. The override takes effect **immediately for newly tagged PII data**. Existing PII-tagged data retains its original retention schedule until expiration (per [$[DPLAT-006]$] AC3).

To request an override, workspace admins must:
1. Submit a ticket referencing [$[DPLAT-013]$]
2. Provide business justification and data classification impact assessment
3. Define scope (specific connectors, data sources, or PII types)
4. Specify duration (temporary overrides expire after 90 days)

All override actions are recorded in the audit log with timestamp, actor identity, tenant ID, previous retention value, and new retention value (per [$[DPLAT-006]$] AC4).

### How Data Is Purged

Data is purged through **automatic anonymization or deletion** according to the configured retention policy. The platform uses **Postgres** as the storage backend for audit logs (per [$[CONFLUENCE]$] ADR-007), with retention management handled via **pg_cron + partitioning**. For PII-tagged data specifically, after the retention period expires, data is automatically anonymized or deleted based on the configured policy (per [$[CONFLUENCE]$] PII Auto-Tagging — Policy and Behavior).

The Salesforce connector also supports a **record deletion propagation policy** (see [$[DPLAT-019]$]): when records are deleted in Salesforce, the connector marks corresponding platform records as "deleted" without immediate removal. These records are retained for the configured retention period (default 90 days) before permanent removal.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Retention Rules

`⚠ conflict`

### Setting Retention for Tagged Data

To set retention for PII-tagged data, you configure the retention period through the **Compliance Vault UI**. The platform applies a **default retention period of 60 days** for all PII-tagged data in connector caches, as specified in [$[DPLAT-006]$]. This default overrides the previously documented 30-day rule from the PII auto-tagging policy (per [$[CONFLUENCE]$] PII Auto-Tagging — Policy and Behavior).

**Important note:** There is a known discrepancy — the bug [$[DPLAT-DEF-04]$] reports that the actual default retention for cached connector data is **90 days**, not the documented 30 days. The 60-day default from DPLAT-006 is intended to resolve this inconsistency.

### Per-Tenant Override

Yes, you can override retention per tenant. Workspace admins can set a **custom retention period (1–365 days)** per tenant via the Compliance Vault UI. The override takes effect **immediately for newly tagged PII data** (per [$[DPLAT-006]$]). Existing PII-tagged data retains its original retention schedule until expiration.

All override actions are recorded in the audit log with:
- Workspace-admin's identity
- Timestamp
- Tenant ID
- Previous retention value
- New retention value

Per-tenant overrides require **compliance officer approval** and are scoped to the requesting tenant (per [$[CONFLUENCE]$] PII Auto-Tagging — Policy and Behavior).

### How Data Is Purged

Data purging follows these rules:

1. **Default retention period:** PII-tagged data is retained for the configured period (default 60 days per DPLAT-006), after which it is **automatically anonymized or deleted** according to the retention policy (per [$[CONFLUENCE]$] PII Auto-Tagging — Policy and Behavior).

2. **Deleted records:** For Salesforce connectors, records marked as "deleted" are retained for the configured retention period (default 90 days per [$[DPLAT-019]$]) before permanent removal. The deletion event is captured in the audit log.

3. **Audit log retention:** The audit log service retains records for **2555 days** (7 years) by default, as configured via the `AUDIT_RETENTION_DAYS` environment variable (per [$[GITHUB]$] audit-log-service README). This is separate from the PII data retention policy.

4. **Storage backend:** The audit log uses **Postgres** with TTL management via `pg_cron` and partitioning for retention enforcement (per [$[CONFLUENCE]$] ADR-007 — Storage Backend for Audit Log).

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Trigger Events

`⚠ conflict`

### How Retention Is Triggered for Tagged Data

Retention for PII-tagged data is triggered **at ingestion time** during the synchronous classification flow. According to [$[PII Auto-Tagging — Policy and Behavior]$], when a connector ingests data:

1. The PII detection engine scans column values using pattern-matching rules and ML classifiers
2. Detected entities are tagged with metadata (type, confidence, position)
3. Tagged content proceeds to storage **with classification preserved**
4. An audit log entry is created for each classification event

The retention clock starts from the moment data is tagged as PII. The platform-wide default retention period for PII-tagged data is **30 days** (per [$[PII Auto-Tagging — Policy and Behavior]$]), after which data is automatically anonymized or deleted according to the configured retention policy.

### Per-Tenant Retention Override

Yes, you can override retention per tenant. The mechanism is described in [$[DPLAT-006]$] (currently **In Progress**):

- **New default**: 60 days for PII-tagged data in connector caches (resolving the inconsistency between the documented 30-day rule and the actual 90-day default reported in [$[DPLAT-DEF-04]$])
- **Custom range**: Workspace admins can set a retention period of **1–365 days** per tenant via the Compliance Vault UI
- **Immediate effect**: Overrides apply immediately to **newly tagged PII data** only; existing PII-tagged data retains its original retention schedule until expiration
- **Audit trail**: Every override action is logged with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value

To request an override, workspace admins must submit a ticket referencing [$[DPLAT-013]$] with business justification and scope definition. All overrides require compliance officer approval and expire after 90 days for temporary configurations.

### How Data Is Purged

Data purging occurs through two mechanisms:

1. **Automatic expiration**: After the configured retention period (default 30 or 60 days depending on version), PII-tagged data is automatically anonymized or deleted. The system uses Postgres with TTL via `pg_cron` + partitioning for retention management (per [$[ADR-007]$]).

2. **Deletion propagation**: For connectors like Salesforce, when a source record is deleted, the connector detects the deletion within 5 minutes and marks the platform record as "deleted" without immediately removing it. The record is retained for the configured retention period (default 90 days per [$[DPLAT-019]$]) before permanent removal.

3. **Audit log archival**: Audit logs are archived to S3 Glacier after 90 days (per [$[DPLAT-036]$]), with custom retention per tenant configurable between 30–365 days. Archived logs remain queryable with a maximum retrieval latency of 4 hours.

**Key note**: The actual default retention for cached connector data is currently **90 days** (per [$[DPLAT-DEF-04]$]), which contradicts the documented 30-day policy. This is being addressed in [$[DPLAT-006]$] which will set a new 60-day default for PII-tagged data.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Automated Purge

`⚠ conflict`

### How to Set Retention for PII-Tagged Data

The platform-wide default retention period for PII-tagged data is **30 days** per the current documentation, after which data is automatically anonymized or deleted according to the configured retention policy [$[PII Auto-Tagging — Policy and Behavior]$]. However, a new default of **60 days** is being introduced via [$[DPLAT-006]$] to resolve inconsistencies between documented policy and observed behavior.

To configure retention:

1. **Default behavior**: The system applies the platform-wide default automatically to all PII-tagged data at ingestion time.
2. **Custom configuration**: Workspace admins can set a custom retention period (1–365 days) per tenant through the Compliance Vault UI [$[DPLAT-006]$].
3. **Immediate effect**: Overrides take effect immediately for **newly tagged PII data** only. Existing PII-tagged data retains its original retention schedule until expiration [$[DPLAT-006]$].

### Per-Tenant Retention Override

Yes, you can override retention per tenant. The override mechanism works as follows:

- **Request process**: Workspace admins submit a ticket referencing [$[DPLAT-013]$] with business justification and data classification impact assessment [$[PII Auto-Tagging — Policy and Behavior]$].
- **Approval required**: All overrides require compliance officer approval and are scoped to the requesting tenant [$[PII Auto-Tagging — Policy and Behavior]$].
- **Auditability**: Override configurations are versioned and auditable. The audit log records each override action with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value [$[DPLAT-006]$].
- **Duration limits**: Temporary overrides expire after 90 days [$[PII Auto-Tagging — Policy and Behavior]$].

### How Data Is Purged (Automated Purge)

The automated purge process operates through the **F-B2: Automated Retention Enforcement** feature of the Compliance Vault [$[Amisol DataPlatform Demo — Product Overview]$]:

1. **Lifecycle management**: The system transitions archived records through lifecycle stages and deletes them when their retention period expires [$[Amisol DataPlatform Demo — Product Overview]$].
2. **Retention policy engine**: A dedicated retention policy engine (targeted for Q2 2026) manages automated archival and deletion jobs, with a retention audit trail tracking who configured what and when [$[Engineering Offsite — Berlin 2026]$].
3. **Postgres-based storage**: For audit logs specifically, retention management leverages `pg_cron` + partitioning for TTL-based cleanup [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$].
4. **Anonymization vs. deletion**: After the retention period expires, PII-tagged data is either automatically anonymized or deleted according to the configured retention policy [$[PII Auto-Tagging — Policy and Behavior]$].

**Important note**: The 60-day default from [$[DPLAT-006]$] currently conflicts with the published 30-day rule in the documentation. A documentation update task is planned as part of the DPLAT-006 implementation.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Legal Holds

`⚠ conflict`

### How to Set Retention for Tagged Data

For PII-tagged data, the platform applies a **default retention period of 60 days** for all newly tagged PII data, as established by [$[DPLAT-006]$]. This overrides the previously documented 30-day rule in the platform-wide policy. The retention is configured through the Compliance Vault service, which uses the `COMPLIANCE_RETENTION_DAYS` environment variable (default 2555 days for audit logs, per [$[compliance-vault]$]), but PII-tagged data in connector caches follows the 60-day default.

To set retention for tagged data:
1. Navigate to **Settings → Compliance Vault** in your tenant
2. Configure baseline PII detection rules
3. The system automatically applies the 60-day retention to all PII-tagged data tagged after the feature deployment (per [$[DPLAT-006]$] AC3)
4. Existing PII-tagged data retains its original retention schedule until expiration

### Can I Override Retention Per Tenant?

**Yes.** Workspace admins can configure per-tenant retention overrides for PII-tagged data through the Compliance Vault UI, as specified in [$[DPLAT-006]$]. The override mechanism allows:

- Setting a custom retention period between **1–365 days** per tenant
- Overrides take effect **immediately** for newly tagged PII data
- All override actions are recorded in the audit log with: workspace-admin identity, timestamp, tenant ID, previous retention value, and new retention value

To request an override, workspace admins must:
1. Submit a ticket referencing [$[DPLAT-013]$]
2. Provide business justification and data classification impact assessment
3. Define scope (specific connectors, data sources, or PII types)
4. Specify duration (temporary overrides expire after 90 days)

The compliance vault evaluates override requests against DPLAT-REQ-06 and DPLAT-REQ-07 requirements before approval (per [$[PII Auto-Tagging — Policy and Behavior]$]).

### How Is Data Purged?

Data purging follows a multi-layered approach:

1. **PII-tagged data in connector caches**: After the configured retention period (default 60 days), data is **automatically anonymized or deleted** according to the retention policy (per [$[PII Auto-Tagging — Policy and Behavior]$]).

2. **Audit logs**: Audit logs are retained for **2555 days (7 years)** by default (per [$[compliance-vault]$] and [$[audit-log-service]$]). After 90 days, audit logs are **automatically archived to S3 Glacier** for cost-effective long-term storage, as implemented in [$[DPLAT-036]$]. Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of 4 hours.

3. **Bulk re-classification**: Compliance officers can run bulk re-classification jobs (per [$[DPLAT-034]$]) to retroactively apply updated retention policies to historical data. The original classification is preserved in the audit log for before/after comparison.

**Important note**: There is a known discrepancy documented in [$[DPLAT-DEF-04]$] — the actual default retention for cached connector data is currently **90 days**, not the documented 30 days. This bug is being addressed, and the new 60-day default for PII-tagged data (from [$[DPLAT-006]$]) is intended to resolve this inconsistency.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Tenant Overrides

`⚠ conflict`

### How to Set Retention for Tagged Data

Per the [PRIMARY] documentation in [$[PII Auto-Tagging — Policy and Behavior]$], the platform-wide default retention period for PII-tagged data is **30 days**. However, per-tenant retention overrides are available through the **tenant configuration API**. Workspace admins can set a custom retention period (1–365 days) per tenant via the Compliance Vault UI, with the override taking effect immediately for newly tagged PII data.

According to [$[DPLAT-006]$], the system is being updated to introduce a **new default of 60 days** for PII-tagged data, resolving an inconsistency where the documented 30-day rule conflicted with an observed 90-day default. This story is currently **In Progress** and assigned to dev2@amisol-demo.example.

### Can I Override Retention Per Tenant?

**Yes.** The override mechanism is explicitly designed for per-tenant customization. Key details from the sources:

- **Override scope**: Workspace admins can configure retention per tenant, not globally. All overrides require **compliance officer approval** and are scoped to the requesting tenant (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Override types available**:
  - Detection suppression (exclude specific PII types)
  - Confidence threshold adjustment (lower the 0.75 default)
  - Custom pattern rules (tenant-specific regex patterns)
- **Request process**: Workspace admins must submit a ticket referencing **DPLAT-013**, providing business justification, scope definition (specific connectors, data sources, or PII types), and duration (temporary overrides expire after 90 days).
- **Audit trail**: All retention override actions are logged in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value (per [$[DPLAT-006]$] acceptance criteria).

### How Is Data Purged?

The retention policy for PII-tagged data follows a **lifecycle approach**:

1. **Default retention**: 30 days (current) → 60 days (planned per [$[DPLAT-006]$]) for PII-tagged data in connector caches.
2. **Automatic action**: After the retention period expires, data is **automatically anonymized or deleted** according to the configured retention policy (per [$[PII Auto-Tagging — Policy and Behavior]$]).
3. **Existing data**: Per [$[DPLAT-006]$] acceptance criteria, existing PII-tagged data retains its original retention schedule until expiration; the new default applies only to data tagged after the feature deployment.
4. **Archival**: The [$[ADR-007]$] mentions that for audit logs, retention is 12 months hot, then archived per tenant retention policy, using Postgres with pg_cron + partitioning for TTL management.

### Important Notes

- The **source of truth** for retention policy is the [$[PII Auto-Tagging — Policy and Behavior]$] document, not the product overview page.
- All retention policy changes are logged in the audit log with timestamp, actor, and justification.
- The 30-day default (and upcoming 60-day default) balances regulatory requirements for data minimization with operational needs for debugging and audit trails.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Scope Definition

`⚠ conflict`

### Setting Retention for Tagged Data

The platform-wide default retention period for PII-tagged data is **30 days** as documented in the PII Auto-Tagging Policy ([$[PII Auto-Tagging — Policy and Behavior]$]), after which data is automatically anonymized or deleted according to the configured retention policy. However, there is a known discrepancy: bug [$[DPLAT-DEF-04]$] reports that the actual observed default retention for cached connector data is **90 days**, not the documented 30 days. This is being addressed in story [$[DPLAT-006]$], which introduces a new default of **60 days** for PII-tagged data in connector caches, resolving the inconsistency.

To set retention for tagged data, the system applies retention at the point of PII classification during ingestion. The PII Auto-Tagging engine scans data synchronously during the ingestion pipeline, tags detected entities with metadata (type, confidence, position), and the tagged content proceeds to storage with classification preserved. The retention clock starts from the moment of tagging.

### Per-Tenant Retention Overrides

Yes, you can override retention per tenant. According to [$[PII Auto-Tagging — Policy and Behavior]$], per-tenant retention overrides are available through the tenant configuration API. Workspace admins may request extended retention periods for specific use cases by submitting a compliance review via [$[DPLAT-006]$]. Story [$[DPLAT-006]$] specifies that workspace admins can set a custom retention period (1–365 days) per tenant via the Compliance Vault UI, with the override taking effect immediately for newly tagged PII data. Existing PII-tagged data retains its original retention schedule until expiration.

The override process requires:
1. Submitting a ticket referencing [$[DPLAT-013]$]
2. Providing business justification and data classification impact assessment
3. Defining scope (specific connectors, data sources, or PII types)
4. Specifying duration (temporary overrides expire after 90 days)

All retention policy changes are logged in the audit log with timestamp, actor, and justification.

### How Data Is Purged

Data purging follows the configured retention policy. For PII-tagged data, after the retention period expires, data is **automatically anonymized or deleted**. The audit log retains records of deletion events. For connector data specifically, story [$[DPLAT-019]$] describes the Salesforce connector's deletion propagation: when a record is deleted in Salesforce, the connector marks the corresponding platform record as "deleted" without immediately removing it, retains it for the configured retention period (default 90 days), then permanently removes it. The audit log captures each deletion event with timestamp, source record ID, tenant identifier, and the user who triggered the source deletion.

The storage backend for audit logs (Postgres per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$]) manages retention via TTL through pg_cron and partitioning, with row-level security for multi-tenant isolation.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Override Logic

`⚠ conflict`

### How to Set Retention for Tagged Data

According to [$[PII Auto-Tagging — Policy and Behavior]$], the platform-wide default retention period for PII-tagged data is **30 days**, after which data is automatically anonymized or deleted. However, [$[DPLAT-006]$] introduces a new default of **60 days** for PII-tagged data in connector caches, overriding the previously documented 30-day rule. This 60-day default applies only to PII data tagged after the feature deployment; existing PII-tagged data retains its original retention schedule until expiration.

To set retention for tagged data, workspace admins can configure a custom retention period (1–365 days) per tenant via the **Compliance Vault UI**. The override takes effect immediately for newly tagged PII data. All retention override actions are recorded in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value.

### Can I Override Retention Per Tenant?

**Yes.** The override mechanism is explicitly designed for per-tenant customization. Per [$[PII Auto-Tagging — Policy and Behavior]$], workspace admins may request extended retention periods for specific use cases by submitting a compliance review via [$[DPLAT-006]$]. All retention policy changes are logged in the audit log with timestamp, actor, and justification.

The override process requires:
1. Submitting a ticket referencing [$[DPLAT-013]$]
2. Providing business justification and data classification impact assessment
3. Defining scope (specific connectors, data sources, or PII types)
4. Specifying duration (temporary overrides expire after 90 days)

The compliance vault evaluates override requests against DPLAT-REQ-06 and DPLAT-REQ-07 requirements before approval.

### How Is Data Purged?

Data purging follows the configured retention policy. Per [$[PII Auto-Tagging — Policy and Behavior]$], after the retention period expires, data is **automatically anonymized or deleted**. The system uses Postgres with TTL via pg_cron and partitioning for retention management (per [$[ADR-007]$]).

For Salesforce connectors specifically, [$[DPLAT-019]$] specifies that records marked as deleted are retained in the platform for the configured retention period (default 90 days) before permanent removal. The audit log captures each deletion event with timestamp, source record ID, tenant identifier, and the user who triggered the source deletion.

**Note on current inconsistency:** [$[DPLAT-DEF-04]$] reports that the actual observed default retention for cached connector data is **90 days**, not the documented 30 days. This bug is currently open and being addressed in [$[DPLAT-006]$], which will set the new default to 60 days for PII-tagged data.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Conflict Resolution

`⚠ conflict`

### Setting Retention for Tagged Data

According to [$[PII Auto-Tagging — Policy and Behavior]$], the platform-wide default retention period for PII-tagged data is **30 days**, after which data is automatically anonymized or deleted. However, this documented default is currently in conflict with actual system behavior.

### The Conflict

There is a documented discrepancy between policy and implementation:

- **Documented policy** ([$[PII Auto-Tagging — Policy and Behavior]$]): Default retention is **30 days** for PII-tagged data.
- **Actual system behavior** ([$[DPLAT-DEF-04]$]): The platform currently applies a default retention of **90 days** for cached connector data, contradicting the documented 30-day policy. This bug is tracked as [$[DPLAT-DEF-04]$] and is currently **Open**, assigned to dev2.

### Resolution Path

The conflict is being addressed through [$[DPLAT-006]$] (currently **In Progress**, assigned to dev2), which introduces a **new default of 60 days** for PII-tagged data. This resolves the inconsistency by establishing a middle ground between the documented 30 days and the actual 90-day behavior. Key resolution details:

1. **New default**: 60 days for all PII-tagged data in connector caches, overriding the previous 30-day rule.
2. **Prospective application**: The new 60-day default applies only to PII data tagged after deployment. Existing PII-tagged data retains its original retention schedule until expiration.
3. **Documentation update**: A separate task will update [$[PII Auto-Tagging — Policy and Behavior]$] to reflect the new 60-day default.

### Per-Tenant Override Mechanism

Yes, you can override retention per tenant. Per [$[DPLAT-006]$], workspace admins can set a custom retention period (1–365 days) per tenant via the Compliance Vault UI. The override takes effect immediately for newly tagged PII data. All override actions are recorded in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value.

### How Data Is Purged

Per [$[PII Auto-Tagging — Policy and Behavior]$], when the retention period expires, PII-tagged data is **automatically anonymized or deleted** according to the configured retention policy. The 30-day (or overridden) window balances regulatory data minimization requirements with operational needs. Additionally, per [$[DPLAT-019]$], records deleted in source systems (e.g., Salesforce) are marked as "deleted" in the platform and retained for the configured retention period before permanent removal.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)

## Permissioning

To set retention for tagged data, you must have the **Workspace Admin** role within the Compliance Vault module. According to [CONFLUENCE] [$[Compliance Vault — Module Overview]$], the Compliance Vault defines three specialized roles, and only Workspace Admins and Compliance Officers have the authority to configure PII rules and retention policies.

### How to Set Retention for Tagged Data

1. **Navigate to the Compliance Vault interface** under **Settings → Compliance Vault** in your tenant workspace.
2. **Configure per-tenant retention overrides** through the Compliance Vault UI. Per [JIRA] [$[DPLAT-006]$], a workspace-admin can set a custom retention period (1–365 days) per tenant, with the override taking effect immediately for newly tagged PII data.
3. **Existing PII-tagged data** retains its original retention schedule until expiration; the new default applies only to data tagged after the feature deployment (per [$[DPLAT-006]$] acceptance criteria).

### Can I Override Retention Per Tenant?

**Yes.** The system supports per-tenant retention overrides through the tenant configuration API. According to [CONFLUENCE] [$[PII Auto-Tagging — Policy and Behavior]$]:

- Workspace admins may request extended retention periods for specific use cases by submitting a compliance review via [$[DPLAT-006]$].
- All retention policy changes are logged in the audit log with timestamp, actor, and justification.
- The default retention period for PII-tagged data is **60 days** (per [$[DPLAT-006]$], which overrides the previously documented 30-day default from Confluence 05).

**Important permissioning note:** All overrides require **compliance officer approval** and are scoped to the requesting tenant. Override configurations are versioned and auditable. To request an override, workspace admins must submit a ticket referencing [$[DPLAT-013]$] with business justification and data classification impact assessment.

### How Is Data Purged?

Data purging follows the configured retention policy and occurs automatically:

1. **Default behavior:** PII-tagged data is retained for the configured period (default 60 days per [$[DPLAT-006]$]), after which data is automatically **anonymized or deleted** according to the retention policy (per [$[PII Auto-Tagging — Policy and Behavior]$]).
2. **Audit log retention:** Audit logs are retained according to the tenant's configured retention policy, with a default of **2555 days** (7 years) as shown in the [$[compliance-vault]$] and [$[audit-log-service]$] configurations.
3. **Deleted records:** For connector data (e.g., Salesforce), records marked as deleted are retained for the configured retention period (default 90 days per [$[DPLAT-019]$]) before permanent removal.

**Permissioning aspect:** Only **Compliance Officers** and **Workspace Admins** can view and manage retention policies. The audit log captures all retention-related actions, ensuring accountability for data purging decisions.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Data Lifecycle Audit

`⚠ conflict`

### Setting Retention for Tagged Data

For PII-tagged data, the platform-wide default retention period is **30 days** per the documented policy in [$[PII Auto-Tagging — Policy and Behavior]$]. After this period, data is automatically anonymized or deleted according to the configured retention policy. However, there is a known discrepancy: bug [$[DPLAT-DEF-04]$] reports that the actual default retention for cached connector data is **90 days**, not 30 days as documented. This is being addressed in story [$[DPLAT-006]$], which introduces a new default of **60 days** for PII-tagged data, overriding the previous 30-day rule.

The retention policy is applied at ingestion: when data passes through the PII detection engine, tagged content proceeds to storage with classification preserved, and the retention clock starts from the tagging event. For audit logs specifically, the default retention is **2555 days (7 years)** per the [$[compliance-vault]$] and [$[audit-log-service]$] configurations, with hot storage for 12 months followed by archival per tenant retention policy (per [$[ADR-007]$]).

### Overriding Retention Per Tenant

Yes, you can override retention per tenant. The override mechanism works as follows:

- **Default override**: Story [$[DPLAT-006]$] (In Progress) allows workspace-admins to set a custom retention period (1–365 days) per tenant via the Compliance Vault UI, with immediate effect for newly tagged PII data. Existing PII-tagged data retains its original schedule until expiration.
- **Audit log archival**: Per [$[DPLAT-036]$], workspace-admins can configure custom retention periods per tenant for audit logs, with a minimum of 30 days and maximum of 365 days. After 90 days, audit logs are automatically archived to S3 Glacier.
- **Override requirements**: Per the [$[PII Auto-Tagging — Policy and Behavior]$], all overrides require compliance officer approval, are scoped to the requesting tenant, and expire after 90 days for temporary overrides. Override configurations are versioned and auditable.
- **Audit trail**: All retention override actions are recorded in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value (per [$[DPLAT-006]$] AC4 and [$[DPLAT-042]$]).

### How Data Is Purged

Data purging follows a multi-stage lifecycle:

1. **Soft deletion**: When data reaches its retention threshold, it is first marked as "deleted" without immediate removal. For example, per [$[DPLAT-019]$], Salesforce record deletions are detected within 5 minutes, marked as "deleted," and retained for the configured retention period (default 90 days) before permanent removal.

2. **Automatic anonymization/deletion**: After the retention period expires, PII-tagged data is automatically anonymized or deleted according to the configured policy. The system uses Postgres with TTL management via `pg_cron` + partitioning for hot data (per [$[ADR-007]$]).

3. **Archival to cold storage**: Audit logs older than 90 days are automatically identified and moved to S3 Glacier storage with appropriate lifecycle policies (per [$[DPLAT-036]$]). Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of 4 hours.

4. **Audit log integrity**: All deletion and archival events are captured in the audit log with immutable hash chaining (SHA-256) to prevent retroactive tampering (per [$[DPLAT-042]$]).

### Data Lifecycle Audit Specifics

For the "Data Lifecycle Audit" subsection, the key auditability features are:

- **Retention policy changes**: All retention policy modifications are logged with timestamp, actor, and justification (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **PII override tracking**: Every manual classification override is automatically captured in the audit log within 500ms, including user ID, timestamp, original classification, new classification, and data record identifier (per [$[DPLAT-042]$]).
- **Export capability**: The Audit Log Export feature (epic [$[DPLAT-EPIC-05]$]) enables compliance officers to retrieve historical audit logs in CSV and JSON formats with filtering by tenant, user, data source, and event type, supporting regulatory reviews and forensic analysis.
- **Retention summary reports**: A daily retention summary report is generated showing the count of logs archived, storage savings, and any failed archival operations (per [$[DPLAT-036]$] AC4).

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-EPIC-05] Audit Log Export](https://demo-jira.local/browse/DPLAT-EPIC-05)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Purge Logs

`⚠ conflict`

### Setting Retention for Tagged Data

The platform-wide default retention period for PII-tagged data is **30 days**, after which data is automatically anonymized or deleted according to the configured retention policy (per [$[PII Auto-Tagging — Policy and Behavior]$]). However, there is a known discrepancy: the bug [$[DPLAT-DEF-04]$] reports that the actual observed default retention for cached connector data is **90 days**, not the documented 30 days. This is being addressed in the upcoming v2.4 release.

The retention contract applies to all tenants unless explicitly overridden. The 30-day window balances regulatory requirements for data minimization with operational needs for debugging and audit trails.

### Per-Tenant Retention Override

Yes, you can override retention per tenant. The story [$[DPLAT-006]$] introduces a new default of **60 days** for PII-tagged data, resolving the inconsistency between the documented 30-day rule and the observed 90-day behavior. Workspace admins can set a custom retention period (1–365 days) per tenant via the Compliance Vault UI, with the override taking effect immediately for newly tagged PII data. Existing PII-tagged data retains its original retention schedule until expiration.

All retention override actions are recorded in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value (per [$[DPLAT-006]$]).

### How Data Is Purged

Data purging for tagged PII data follows these mechanisms:

1. **Automatic expiration**: After the configured retention period (default 30 days, or per-tenant override), PII-tagged data is automatically anonymized or deleted according to the retention policy (per [$[PII Auto-Tagging — Policy and Behavior]$]).

2. **Audit log archival**: For audit logs specifically, the system archives logs to **S3 Glacier** after 90 days of retention (per [$[DPLAT-036]$]). Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of 4 hours. Workspace admins can configure custom retention periods per tenant, with a minimum of 30 days and maximum of 365 days.

3. **Record deletion propagation**: For Salesforce connectors, records marked as deleted are retained for the configured retention period (default 90 days) before permanent removal (per [$[DPLAT-019]$]).

4. **Storage backend**: The audit log uses **Postgres** for v2 storage, with retention management via pg_cron and partitioning (per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$]). ClickHouse may be evaluated for v3 if performance or cost thresholds are exceeded.

### Key Configuration Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `COMPLIANCE_RETENTION_DAYS` | Audit log retention period | 2555 days (7 years) |
| `AUDIT_RETENTION_DAYS` | Number of days to retain audit records | 2555 days |

Note: The `COMPLIANCE_RETENTION_DAYS` and `AUDIT_RETENTION_DAYS` defaults of 2555 days (7 years) apply to audit logs, while the PII-tagged data retention is governed by the 30-day (or per-tenant override) policy described above.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)

## Retention History

`⚠ conflict`

### How to Set Retention for Tagged Data

According to the PII Auto-Tagging Policy [$[PII Auto-Tagging — Policy and Behavior]$], the platform-wide default retention period for PII-tagged data is **30 days**, after which data is automatically anonymized or deleted according to the configured retention policy. This retention contract applies to all tenants unless explicitly overridden.

However, based on the Jira ticket [$[DPLAT-006]$], this default is being updated to **60 days** for PII-tagged data in connector caches, resolving a documented inconsistency where the actual observed default was 90 days (per [$[DPLAT-DEF-04]$]).

To set retention for tagged data:
- The system applies the default retention period automatically to all newly tagged PII data
- For existing PII-tagged data, the original retention schedule is maintained until expiration
- The retention period is configured via the `COMPLIANCE_RETENTION_DAYS` environment variable in the compliance-vault service (default 2555 days for audit logs, per [$[compliance-vault — README]$])

### Can I Override Retention Per Tenant?

**Yes.** Per-tenant retention overrides are available through the tenant configuration API, as documented in the PII Auto-Tagging Policy [$[PII Auto-Tagging — Policy and Behavior]$]. Workspace admins can:

1. Set a custom retention period (1–365 days) per tenant via the Compliance Vault UI (per [$[DPLAT-006]$])
2. The override takes effect immediately for newly tagged PII data
3. All override actions are recorded in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value

To request an extended retention period for specific use cases, workspace admins must submit a compliance review via [$[DPLAT-006]$]. All retention policy changes are logged in the audit log with timestamp, actor, and justification.

### How Is Data Purged?

Data purging for tagged data follows the configured retention policy:

- **Default behavior**: After the retention period expires (30 days platform-wide, or 60 days per [$[DPLAT-006]$]), PII-tagged data is automatically **anonymized or deleted** according to the retention policy
- **Per-tenant overrides**: Custom retention periods (1–365 days) determine when data is purged for that tenant
- **Existing data**: Data tagged before a retention policy change retains its original schedule until expiration; only newly tagged data follows the updated policy
- **Audit logs**: The audit-log-service retains records for 2555 days (7 years) by default, as configured via the `AUDIT_RETENTION_DAYS` environment variable (per [$[audit-log-service — README]$])
- **Storage backend**: Postgres is used for v2 audit log storage, with TTL management via pg_cron and partitioning (per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$])

The purge process ensures compliance with data minimization principles while maintaining audit trails for regulatory purposes.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Compliance Reporting

`⚠ conflict`

For **Compliance Reporting** purposes, retention for tagged (PII) data is configured through the Compliance Vault module. The system applies a **default retention period of 60 days** for all PII-tagged data in connector caches, as specified in [$[DPLAT-006]$]. This overrides the previously documented 30-day platform-wide rule from the PII Auto-Tagging policy.

### Per-Tenant Override Mechanism

Yes, you can override retention per tenant. Workspace admins can set a **custom retention period (1–365 days)** per tenant via the Compliance Vault UI. According to [$[DPLAT-006]$], the override takes effect immediately for newly tagged PII data, while existing PII-tagged data retains its original retention schedule until expiration. All override actions are recorded in the audit log with the workspace admin's identity, timestamp, tenant ID, previous retention value, and new retention value.

Per the [$[PII Auto-Tagging — Policy and Behavior]$] documentation, workspace admins may request extended retention periods for specific use cases by submitting a compliance review via [$[DPLAT-006]$]. Override configurations are versioned and auditable, and temporary overrides expire after 90 days.

### Data Purge Process

Data is purged through **Automated Retention Enforcement (F-B2)**. According to the [$[Compliance Vault — Module Overview]$], the system applies retention policies to archived records, transitioning them through lifecycle stages and deleting them when their retention period expires. For PII-tagged data specifically, the retention contract states that after the configured period (default 30 days per the PII policy, or the overridden value), data is **automatically anonymized or deleted** according to the configured retention policy.

The audit log storage itself uses **Postgres** (per [$[ADR-007]$]), with retention management handled via **pg_cron + partitioning** for TTL-based data lifecycle. The default retention for audit log records is **2555 days (7 years)**, as shown in the [$[audit-log-service]$] and [$[compliance-vault]$] configurations.

### Important Note on Current Discrepancy

A known issue ([$[DPLAT-DEF-04]$]) reports that the actual observed default retention for cached connector data is **90 days**, not the documented 30 days. This is being addressed in [$[DPLAT-006]$], which introduces a new 60-day default for PII-tagged data. For compliance reporting, you should verify the actual retention period applied in your tenant and manually configure it if needed until the fix is deployed.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Deletion Verification

`⚠ conflict`

### How to Set Retention for Tagged Data

For PII-tagged data, the platform applies a **default retention period of 60 days** for all newly tagged data after the DPLAT-006 feature deployment (per [$[DPLAT-006]$]). This overrides the previously documented 30-day rule. The retention is configured via the `COMPLIANCE_RETENTION_DAYS` environment variable in the compliance-vault service, which defaults to 2555 days for audit logs specifically (per [$[compliance-vault]$] README), while PII-tagged data in connector caches follows the 60-day default.

**Important note**: There is a known discrepancy — the bug [$[DPLAT-DEF-04]$] reports that the actual default retention for cached connector data is **90 days**, not the documented 30 or 60 days. This is an open issue being addressed.

### Can I Override Retention Per Tenant?

**Yes.** Workspace admins can configure per-tenant retention overrides through the Compliance Vault UI (per [$[DPLAT-006]$]):

- Custom retention periods can be set **1–365 days** per tenant
- Overrides take effect **immediately for newly tagged PII data**
- Existing PII-tagged data retains its original retention schedule until expiration
- All override actions are recorded in the audit log with: workspace-admin identity, timestamp, tenant ID, previous retention value, and new retention value

The override mechanism is also described in the [$[PII Auto-Tagging — Policy and Behavior]$] documentation, which notes that workspace admins may request extended retention periods by submitting a compliance review via DPLAT-006.

### How Is Data Purged? (Deletion Verification Aspect)

The deletion verification process works as follows:

1. **Automatic expiration**: After the configured retention period expires, PII-tagged data is **automatically anonymized or deleted** according to the retention policy (per [$[PII Auto-Tagging — Policy and Behavior]$]).

2. **Deletion propagation**: For Salesforce connectors specifically, when a record is deleted in the source system, the connector detects the deletion within 5 minutes and marks the corresponding platform record as "deleted" without immediately removing it (per [$[DPLAT-019]$]). These marked records are retained for the configured retention period (default 90 days per DPLAT-019) before permanent removal.

3. **Audit trail for deletion**: All deletion events are captured in the audit log with timestamp, source record ID, tenant identifier, and the user who triggered the source deletion. Workspace admins can view and filter deleted records in the connector's data source view.

4. **Verification mechanism**: The audit log provides a complete, tamper-evident record of all retention-related actions, including:
   - PII override decisions (per [$[DPLAT-042]$])
   - Retention policy changes
   - Deletion events
   - The audit log uses SHA-256 hash chaining to prevent retroactive tampering

**Key takeaway for Deletion Verification**: To verify that data has been properly purged according to retention policies, compliance officers should:
- Check the audit log for deletion events filtered by date range and action type
- Review the connector health monitor for deleted records status
- Use the audit log export feature (F-B2) to generate compliance reports showing when data was marked for deletion and when it was permanently removed

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)

## Recovery & Compliance

`⚠ conflict`

### Setting Retention for Tagged Data

For the **Recovery & Compliance** context, PII-tagged data is governed by a platform-wide retention contract. According to [$[PII Auto-Tagging — Policy and Behavior]$], the default retention period for PII-tagged data is **30 days**, after which data is automatically anonymized or deleted according to the configured retention policy. This 30-day window balances regulatory requirements for data minimization with operational needs for debugging and audit trails.

However, there is a known discrepancy: [$[DPLAT-DEF-04]$] reports that the actual observed default retention for cached connector data is **90 days**, not 30 days as documented. This bug is currently **Open** and poses a compliance risk, as it exceeds the documented data minimization policy. The fix is being addressed through [$[DPLAT-006]$], which introduces a new default of **60 days** for PII-tagged data, resolving the inconsistency.

### Per-Tenant Retention Override

Yes, you can override retention per tenant. Per [$[PII Auto-Tagging — Policy and Behavior]$], workspace admins may request extended retention periods for specific use cases by submitting a compliance review via [$[DPLAT-006]$]. The override mechanism works as follows:

- **Default**: 60 days (per DPLAT-006, currently In Progress)
- **Custom range**: 1–365 days per tenant
- **Application**: Overrides take effect immediately for newly tagged PII data; existing PII-tagged data retains its original retention schedule until expiration
- **Audit trail**: All retention override actions are recorded in the audit log with the workspace admin's identity, timestamp, tenant ID, previous retention value, and new retention value
- **Approval**: Overrides require compliance officer approval and are scoped to the requesting tenant

### How Data Is Purged

From a **Recovery & Compliance** perspective, data purging follows these principles:

1. **Automatic deletion/anonymization**: After the configured retention period expires, PII-tagged data is automatically anonymized or deleted according to the retention policy (per [$[PII Auto-Tagging — Policy and Behavior]$]).

2. **Audit log preservation**: Even after data is purged, the audit log retains immutable records of all classification events, access events, and retention policy changes. Per [$[compliance-vault]$] and [$[audit-log-service]$], audit logs are retained for **2555 days** (7 years), independent of the data retention period.

3. **Deleted record handling**: For connector data (e.g., Salesforce), per [$[DPLAT-019]$], records marked as deleted are retained in the platform for the configured retention period (default 90 days) before permanent removal. The audit log captures the deletion event with timestamp, source record ID, tenant identifier, and the user who triggered the source deletion.

4. **Bulk re-classification**: For recovery scenarios, [$[DPLAT-034]$] (To Do, v2.5) will allow compliance officers to run bulk re-classification jobs on historical data, applying updated PII auto-tagging rules while preserving original classifications in the audit log for before/after comparison.

### Key Compliance Considerations

- **Regulatory alignment**: The 30-day (documented) or 60-day (planned) retention supports GDPR data minimization principles and BDSG requirements
- **Audit integrity**: All retention changes, overrides, and purges are logged immutably for compliance reporting
- **Recovery capability**: The audit log provides a complete historical trail even after data is purged, enabling compliance officers to reconstruct access patterns and policy changes

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)

## Backup Constraints

`⚠ conflict`

### How to Set Retention for Tagged Data

For PII-tagged data, the platform-wide default retention period is **30 days**, after which data is automatically anonymized or deleted according to the configured retention policy (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior). However, there is a known discrepancy: [JIRA] DPLAT-DEF-04 reports that the actual observed default for cached connector data is **90 days**, not the documented 30 days. This bug is currently open and being addressed.

To set retention for tagged data, you configure the `COMPLIANCE_RETENTION_DAYS` environment variable in the compliance-vault service (per [GITHUB] compliance-vault — README). The default value for this variable is **2555 days** (7 years) for audit logs, but this applies to audit log retention, not PII-tagged data retention specifically.

For PII-tagged data in connector caches, [JIRA] DPLAT-006 introduces a new default of **60 days** (currently In Progress for v2.4). This resolves the inconsistency between the documented 30-day rule and the observed 90-day behavior.

### Can I Override Retention Per Tenant?

**Yes.** Per-tenant retention overrides are available through two mechanisms:

1. **Tenant Configuration API**: Workspace admins can request extended retention periods for specific use cases by submitting a compliance review via [JIRA] DPLAT-006. All retention policy changes are logged in the audit log with timestamp, actor, and justification (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior).

2. **Compliance Vault UI**: Per [JIRA] DPLAT-006 (Acceptance Criterion 2), a workspace-admin can set a custom retention period (1–365 days) per tenant via the Compliance Vault UI. The override takes effect immediately for newly tagged PII data. Existing PII-tagged data retains its original retention schedule until expiration.

3. **Override mechanisms for auto-tagging behavior** (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior):
   - Detection suppression (exclude specific PII types)
   - Confidence threshold adjustment (lower the 0.75 threshold)
   - Custom pattern rules (tenant-specific regex patterns)

All overrides require compliance officer approval and are scoped to the requesting tenant. Override configurations are versioned and auditable.

### How Is Data Purged?

Data purging follows a **retention contract** approach:

- **Default retention**: 30 days for PII-tagged data (documented), though [JIRA] DPLAT-DEF-04 reports the actual default is 90 days for cached connector data. [JIRA] DPLAT-006 will set a new default of 60 days for PII-tagged data.
- **Automatic purging**: After the configured retention period expires, data is automatically anonymized or deleted according to the retention policy (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior).
- **Audit log retention**: The audit-log-service retains records for **2555 days** (7 years) by default, configurable via `AUDIT_RETENTION_DAYS` (per [GITHUB] audit-log-service — README). Postgres is used for v2 storage, with TTL management via `pg_cron` + partitioning (per [CONFLUENCE] ADR-007).
- **Deletion propagation**: For Salesforce connectors, [JIRA] DPLAT-019 specifies that deleted records are marked as "deleted" without immediate removal, retained for the configured retention period (default 90 days) before permanent removal.

### Backup Constraints Summary

The key backup constraint is that **retention policies are applied at the data level, not at the backup level**. The system does not have separate backup retention policies; instead, data purging is driven by the configured retention periods for PII-tagged data and audit logs. The 30-day (or 60-day after DPLAT-006) default for PII-tagged data ensures data minimization, while the 2555-day audit log retention ensures compliance with regulatory requirements. Per-tenant overrides allow flexibility but are subject to compliance review and audit logging.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Legal Hold Management

`⚠ conflict` `⚠ stale`

### Setting Retention for Tagged Data

For PII-tagged data under legal hold management, the platform applies a **default retention period of 60 days** for all newly tagged PII data in connector caches, as specified in [$[DPLAT-006]$]. This overrides the previously documented 30-day platform-wide rule from [$[PII Auto-Tagging — Policy and Behavior]$]. The retention period is configured via the `COMPLIANCE_RETENTION_DAYS` environment variable in the compliance-vault service, which defaults to 2555 days (7 years) for audit logs specifically (per [$[compliance-vault — README]$]).

To set retention for tagged data:
1. **Default behavior**: PII-tagged data is automatically retained for 60 days from the time of tagging, after which it is anonymized or deleted according to the configured retention policy.
2. **Custom retention**: Workspace admins can set a custom retention period (1–365 days) per tenant via the Compliance Vault UI. This override takes effect immediately for newly tagged PII data, while existing PII-tagged data retains its original schedule until expiration (per [$[DPLAT-006]$]).
3. **Legal hold considerations**: For data under legal hold, the retention policy must be configured to prevent automatic purging. The system supports per-tenant overrides that can extend retention beyond the default, but all changes are logged in the audit trail with timestamp, actor identity, and justification.

### Overriding Retention Per Tenant

Yes, retention can be overridden per tenant. The override mechanism works as follows:

- **How to request**: Workspace admins submit a compliance review request via [$[DPLAT-006]$] or a ticket referencing [$[DPLAT-013]$] for classifier-related overrides. The request must include business justification, data classification impact assessment, scope definition (specific connectors, data sources, or PII types), and duration (temporary overrides expire after 90 days).
- **Approval process**: All overrides require compliance officer approval and are evaluated against requirements DPLAT-REQ-06 and DPLAT-REQ-07 before approval (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Audit trail**: Each override action is recorded in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value (per [$[DPLAT-006]$]).
- **Customization scope**: Overrides can include detection suppression (exclude specific PII types), confidence threshold adjustment (lower the 0.75 threshold), and custom pattern rules for tenant-specific data formats (per [$[PII Auto-Tagging — Policy and Behavior]$]).

### How Data Is Purged

Data purging for legal hold management follows a multi-stage process:

1. **Automatic expiration**: After the configured retention period (default 60 days for PII-tagged data), data is automatically anonymized or deleted according to the retention policy. The 30-day window documented in [$[PII Auto-Tagging — Policy and Behavior]$] is being superseded by the 60-day default from [$[DPLAT-006]$].
2. **Audit log archival**: Audit logs are archived to S3 Glacier after 90 days of retention (per [$[DPLAT-036]$]). Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of 4 hours. Workspace admins can configure custom retention periods per tenant (30–365 days minimum/maximum).
3. **Bulk re-classification**: Compliance officers can run bulk re-classification jobs on historical data to retroactively apply updated retention policies (per [$[DPLAT-034]$]). The original classification is preserved in the audit log for before/after comparison.
4. **Legal hold preservation**: For data under legal hold, the system must be configured to prevent automatic purging. This requires setting a per-tenant retention override that extends beyond the standard expiration, with all changes logged for compliance verification.

**Important note**: There is a known discrepancy — the platform currently applies a 90-day default retention for cached connector data, contradicting the documented 30-day policy (per [$[DPLAT-DEF-04]$]). The [$[DPLAT-006]$] story introduces a 60-day default for PII-tagged data to resolve this inconsistency. For legal hold management, ensure that per-tenant overrides are explicitly configured rather than relying on defaults.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Data Recovery

`⚠ conflict`

### How to Set Retention for Tagged Data

For PII-tagged data, the platform-wide default retention period is **30 days** per the documented policy in [$[PII Auto-Tagging — Policy and Behavior]$]. After this period, PII-tagged data is automatically anonymized or deleted according to the configured retention policy. However, a bug ([$[DPLAT-DEF-04]$]) has been identified where the actual default retention for cached connector data is **90 days**, not the documented 30 days. This discrepancy is being addressed in story [$[DPLAT-006]$], which introduces a new default of **60 days** for PII-tagged data.

To set retention for tagged data:
- The default retention applies automatically to all newly tagged PII data after the feature deployment.
- Existing PII-tagged data retains its original retention schedule until expiration (based on [$[DPLAT-006]$]).
- For audit logs, the default retention is **2555 days (7 years)** per the [$[compliance-vault]$] and [$[audit-log-service]$] configurations.

### Can I Override Retention Per Tenant?

**Yes.** Workspace admins can configure per-tenant retention overrides through the Compliance Vault UI or API. Key details from [$[DPLAT-006]$]:
- Custom retention periods can be set between **1–365 days** per tenant.
- Overrides take effect immediately for **newly tagged PII data**.
- All override actions are recorded in the audit log with the workspace-admin's identity, timestamp, tenant ID, previous retention value, and new retention value.
- Override requests require compliance officer approval and are scoped to the requesting tenant (per [$[PII Auto-Tagging — Policy and Behavior]$]).

For audit logs specifically, workspace admins can configure custom retention periods per tenant with a minimum of **30 days** and maximum of **365 days** (based on [$[DPLAT-036]$]).

### How Is Data Purged?

Data purging follows a multi-stage process:

1. **Soft deletion**: When records are deleted from source systems (e.g., Salesforce), the connector marks corresponding platform records as "deleted" without immediately removing them. These records are retained for the configured retention period (default 90 days per [$[DPLAT-019]$]) before permanent removal.

2. **Automatic purging**: After the retention period expires, PII-tagged data is automatically anonymized or deleted according to the configured retention policy (based on [$[PII Auto-Tagging — Policy and Behavior]$]).

3. **Audit log archival**: Audit logs older than **90 days** are automatically archived to **S3 Glacier** cold storage for cost-effective long-term retention. Archived logs remain queryable with a maximum retrieval latency of 4 hours (based on [$[DPLAT-036]$]).

4. **Retention summary reports**: A daily report is generated showing the count of logs archived, storage savings, and any failed archival operations (based on [$[DPLAT-036]$]).

**Important note for Data Recovery**: The 90-day default retention for cached connector data (identified in [$[DPLAT-DEF-04]$]) means that data may persist longer than documented. This discrepancy is being resolved through [$[DPLAT-006]$], which will standardize the default to 60 days for PII-tagged data. For data recovery purposes, workspace admins should verify their tenant's actual retention configuration rather than relying solely on documented defaults.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)

## Audit Trail

`⚠ conflict`

To set retention for tagged data in the Audit Trail context, you configure the **audit log retention period** via the `AUDIT_RETENTION_DAYS` environment variable in the audit-log-service, which defaults to **2555 days** (7 years) per [GITHUB] audit-log-service. This applies to all audit events, including those related to PII-tagged data access and modifications.

For **PII-tagged data specifically**, the platform-wide default retention is **30 days** per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior, after which data is automatically anonymized or deleted. However, note that [JIRA] DPLAT-DEF-04 reports the actual observed default for cached connector data is **90 days**, contradicting the documented 30-day policy. [JIRA] DPLAT-006 introduces a new default of **60 days** for PII-tagged data in connector caches, resolving this inconsistency.

### Per-Tenant Override

Yes, you can **override retention per tenant** for PII-tagged data. Per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior, workspace admins can configure custom retention periods through the tenant configuration API, with all changes logged in the audit log. [JIRA] DPLAT-006 specifies that workspace admins can set a custom retention period of **1–365 days** per tenant via the Compliance Vault UI, taking effect immediately for newly tagged PII data. Existing PII-tagged data retains its original schedule until expiration.

For audit logs specifically, [JIRA] DPLAT-036 allows workspace admins to configure custom retention periods per tenant with a **minimum of 30 days and maximum of 365 days**, after which logs older than 90 days are automatically archived to S3 Glacier.

### How Data Is Purged

Data purging for the Audit Trail follows a **multi-stage lifecycle**:

1. **Hot retention (Postgres)**: Audit logs are stored in Postgres per [CONFLUENCE] ADR-007, with retention managed via `pg_cron` and partitioning. The default retention is 2555 days (7 years) per [GITHUB] audit-log-service.

2. **Archival to cold storage**: Per [JIRA] DPLAT-036, audit logs older than **90 days** are automatically identified and moved to **S3 Glacier** storage using lifecycle policies. Archived logs remain queryable via the Audit Log Export feature with a maximum retrieval latency of 4 hours.

3. **Permanent deletion**: For PII-tagged data, after the configured retention period expires, data is **automatically anonymized or deleted** per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior. For audit logs, the archival to S3 Glacier serves as long-term storage, with the original Postgres records being purged according to the retention policy.

4. **Audit trail of purges**: All retention policy changes and data purging actions are themselves logged in the audit log with timestamp, actor, and justification per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior. [JIRA] DPLAT-042 ensures all PII override decisions are automatically captured in the audit log with immutable hash chaining using SHA-256.

**Key takeaway**: For the Audit Trail specifically, you set retention via `AUDIT_RETENTION_DAYS` (default 2555 days), can override per tenant (30–365 days per [JIRA] DPLAT-036), and data is purged by first archiving to S3 Glacier after 90 days, then eventually removed from hot storage according to the configured retention period.

**Sources:**
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-036] Audit Log — archival to S3 Glacier after 90 days](https://demo-jira.local/browse/DPLAT-036)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Engineering Offsite — Berlin 2026](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5f292a2a1efe)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-REQ-18] Audit Log — write throughput sustains 10k events/sec per tenant](https://demo-jira.local/browse/DPLAT-REQ-18)
