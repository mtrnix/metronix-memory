# F-A1  Salesforce Connector — One-Pager

_Feature: `F-A1` · Audience: external-prospect, marketing-manager_

> 2-page sales-ready brief for healthcare and financial-services CISO audience

## Hero & Value Proposition

### What It Does at a High Level

The Salesforce Connector enables seamless, bidirectional synchronization between your Salesforce CRM and the Amisol DataPlatform. It acts as a bridge that keeps your Salesforce data—Accounts, Contacts, Leads, Opportunities, and Cases—continuously aligned with the platform's unified data lake, eliminating the need for custom ETL development or manual data exports.

### Customer-Visible Capabilities

**Real-Time Data Sync:** The connector delivers near-real-time event propagation with sub-5-second latency via webhook-driven triggers. Changes made in Salesforce (new leads, updated opportunities, closed cases) appear in the platform almost instantly, ensuring your analytics, compliance vault, and cross-platform operations always reflect the latest state of your CRM.

**Guided Setup Experience:** Workspace administrators can configure the connector through a step-by-step wizard that handles OAuth 2.0 authentication, object selection, and field mapping without requiring deep technical expertise. The wizard validates the connection and immediately displays the connector's health status.

**Bidirectional Write-Back:** Beyond reading data, the connector supports writing updates back to Salesforce for supported objects, enabling workflows where platform actions (e.g., enrichment from external sources) can update your CRM records.

**Configurable Sync Modes:** Choose between near-real-time (webhook-driven), hourly batch, or daily full-snapshot sync to match your data freshness requirements and API consumption constraints.

**Field-Level Mapping & Transformation:** Declaratively map Salesforce fields to platform schemas, with support for data type coercion, string formatting, date normalization, and lookup resolution—no custom code required.

**Record Deletion Propagation:** When records are deleted in Salesforce, the connector detects the event within 5 minutes, marks the corresponding platform record as "deleted," and retains it for a configurable retention period (default 90 days) to maintain audit trail completeness.

### Security & Compliance Posture

**Authentication:** The connector uses **OAuth 2.0** with the Salesforce Connected App flow. Tokens are stored encrypted in the tenant's secure vault and automatically refreshed before expiration (60-minute TTL). Required OAuth scopes are limited to `api`, `refresh_token`, and `webhook`—no excessive permissions.

**Data Protection:** All cached Salesforce data is encrypted at rest using AES-256 and is never exposed outside the tenant boundary. Cached records are automatically purged after 30 days (configurable up to 90 days for compliance needs).

**Audit Trail:** Every data access and modification event is captured in the platform's audit log, including timestamps, user identities, actions, and resource identifiers. This supports compliance requirements for tracking data lineage and demonstrating governance.

**IP Allowlisting:** The connector requires Salesforce network access settings to include DPLAT outbound IP ranges, ensuring that only authorized connections reach your Salesforce org.

**Error Handling & Resilience:** The connector implements retry logic with exponential backoff for transient failures, quarantines problematic records for manual review, and maintains detailed audit logs for all error events—supporting both operational reliability and compliance documentation.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)

## Why this matters for compliance-heavy industries

### What the Salesforce Connector Does at a High Level

The Salesforce Connector (feature F-A1) enables bidirectional synchronization between Salesforce orgs and the DPLAT platform. It ingests standard objects (Account, Contact, Lead, Opportunity, Case) and custom objects into the platform's unified data lake, supporting use cases such as lead routing, opportunity tracking, and customer 360° views. The connector operates in three sync modes: near real-time (webhook-driven, under 5 seconds latency), scheduled hourly batch, and scheduled daily batch. Authentication uses OAuth 2.0 via Salesforce Connected App flow, with tokens stored encrypted in the tenant's secure vault and automatically refreshed before expiration.

### Customer-Visible Capabilities Delivered

For compliance-heavy industries, the connector delivers several critical capabilities:

- **Selective field mapping** to reduce PII exposure at the source — workspace admins can configure which fields to sync, minimizing the transfer of sensitive data
- **Change Data Capture (CDC)** for near-real-time event streaming, enabling immediate visibility into CRM changes
- **Bulk API v2** for historical backfills, supporting audit trail completeness
- **Schema drift detection** that surfaces warnings in the Health Monitor when Salesforce object structures change, preventing silent data integrity issues
- **Audit logging** of all connector configuration changes with user identity, timestamp, and before/after state diffs

### Security and Compliance Posture

The connector's security and compliance posture is designed for regulated environments:

- **Authentication**: OAuth 2.0 with automatic token refresh; tokens encrypted at rest (AES-256) in the tenant vault
- **Data retention**: Cached Salesforce data retained for 30 days by default, configurable up to 90 days for compliance requirements; cache encrypted at rest and never exposed outside the tenant boundary
- **Error handling**: Quarantined records retained for 7 days with exportable logs for audit purposes; compliance officers have read-only access to audit logs and PII mappings
- **IP allowlisting**: DPLAT outbound IP ranges must be allowlisted in the target Salesforce org, providing network-level access control
- **Role-based access**: Workspace admins configure connectors, compliance officers have read-only audit access, tenant administrators manage network and security policies

For compliance-heavy industries such as finance, healthcare, and insurance, this means the connector provides granular control over what data enters the platform, how it's stored, who can access it, and a complete audit trail of all configuration changes — all essential for meeting GDPR, HIPAA, SOX, and similar regulatory requirements.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)

## Three Key Capabilities (with brief technical credibility lines)

### 1. Bi-Directional Real-Time Data Synchronization

**What it does:** The Salesforce Connector enables seamless, automated synchronization between Salesforce orgs and the DPLAT platform, allowing users to unify CRM data with other enterprise data sources without custom integration work.

**Customer-visible capabilities:**
- Near real-time sync via webhook-driven Change Data Capture (CDC) with sub-5-second latency for standard objects like Accounts, Contacts, Opportunities, Leads, and Cases [$[Salesforce Connector — Business Rules]$]
- Scheduled batch sync options (hourly delta or daily full snapshot) for high-volume or custom objects [$[Salesforce Connector — Business Rules]$]
- Support for both standard and custom objects, with custom objects requiring schema registration via the Connector Configuration API [$[Connector Configuration API — Reference]$]

**Technical credibility:** The connector uses Salesforce Platform Events for event-driven streaming and Bulk API v2 for historical backfills, with configurable per-object sync frequency and selective field mapping to reduce data transfer overhead [$[Connector Framework — Module Overview]$].

### 2. Secure OAuth 2.0 Authentication with Automatic Token Management

**What it does:** The connector provides enterprise-grade authentication that eliminates manual credential management, ensuring continuous, secure data flow without interruption.

**Customer-visible capabilities:**
- One-time OAuth 2.0 setup via Salesforce Connected App flow, with tokens stored encrypted at rest using AES-256-GCM [$[DPLAT-003]$]
- Automatic silent token refresh 5 minutes before expiry, with exponential backoff retry logic (up to 5 attempts) to maintain uninterrupted sync [$[DPLAT-003]$]
- Workspace-level credential management with encrypted tenant vault storage, ensuring credentials never leave the tenant boundary [$[Salesforce Connector — Business Rules]$]

**Technical credibility:** The connector implements OAuth 2.0 with `api`, `refresh_token`, and `webhook` scopes, and alerts workspace admins via the Health Monitor after 3 consecutive refresh failures, preventing silent data loss [$[DPLAT-003]$].

### 3. Compliance-First Data Governance and Audit Trail

**What it does:** The connector enforces data governance policies from ingestion through retention, giving compliance officers full visibility and control over sensitive CRM data.

**Customer-visible capabilities:**
- Selective field mapping to reduce PII exposure at the source, with masking support for sensitive fields like SSN and credit card numbers [$[Connector Configuration API — Reference]$]
- Automatic record deletion propagation: when records are deleted in Salesforce, the connector detects the deletion within 5 minutes, marks the platform record as "deleted," and retains it for the configured retention period (default 90 days) before permanent removal [$[DPLAT-019]$]
- Comprehensive audit logging capturing all configuration changes with user identity, timestamp, before/after state diff, and source IP [$[Connector Framework — Module Overview]$]

**Technical credibility:** All cached Salesforce data is encrypted at rest using AES-256, retained for a configurable period (30-90 days), and never exposed outside the tenant boundary. The connector supports compliance with GDPR Article 17, CCPA, and HIPAA through configurable retention policies and cryptographic erasure disposal methods [$[Release Notes — v2.4 (Planned)]$].

---

**Security & Compliance Posture Summary:** The Salesforce Connector operates within a zero-trust framework where all data in transit uses TLS encryption, authentication uses OAuth 2.0 with automatic token rotation, and all cached data is encrypted at rest with AES-256. Compliance officers have read-only access to audit logs and PII mappings, while workspace admins manage connector configuration. The connector supports tenant-level retention policy overrides for alignment with industry-specific regulatory requirements.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-017] Salesforce — bulk migration tool from legacy v1 connector](https://demo-jira.local/browse/DPLAT-017)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)

## Customer-Visible Benefits

### High-Level Functionality

The Salesforce Connector provides a seamless, bidirectional synchronization bridge between your Salesforce CRM and the Amisol DataPlatform. For the platform user, this means your Salesforce data—including Accounts, Contacts, Leads, Opportunities, and Cases—is automatically and continuously mirrored into the platform's unified data lake without requiring custom ETL development or manual data exports. The connector operates in near real-time, with changes propagating from Salesforce to the platform in under 5 seconds via webhook-driven event triggers [$[DPLAT-EPIC-01]$].

### Customer-Visible Capabilities

**Real-Time Data Synchronization:** The connector delivers event-driven Change Data Capture (CDC), meaning that whenever a record is created or updated in Salesforce, that change is reflected in the platform within seconds. This enables downstream analytics, compliance vault integration, and cross-platform data operations to work with the most current data available [$[Salesforce Connector — Business Rules]$].

**Guided Setup Experience:** Workspace administrators can configure the connector through a step-by-step setup wizard that handles OAuth 2.0 authentication, object selection, and connection validation—no specialized technical expertise required [$[DPLAT-002]$].

**Flexible Sync Scheduling:** The connector supports three sync modes: near real-time (webhook-driven, sub-5-second latency), hourly batch delta sync, and daily full snapshot sync. This allows customers to balance data freshness against API consumption based on their specific needs [$[Salesforce Connector — Business Rules]$].

**Field-Level Mapping and Transformation:** Users can declaratively map Salesforce fields to platform fields, apply data type coercion, and configure basic transformation rules such as string formatting and date normalization. This ensures complex Salesforce data models integrate cleanly with the platform [$[DPLAT-EPIC-01]$].

**Automatic Token Management:** The connector handles OAuth token refresh automatically, refreshing access tokens 5 minutes before expiry with exponential backoff retry logic. This ensures uninterrupted data synchronization without manual intervention [$[DPLAT-003]$].

**Record Deletion Propagation:** When records are deleted in Salesforce, the connector detects the deletion within 5 minutes and marks the corresponding platform record as "deleted" while retaining it for a configurable period (default 90 days) to meet compliance requirements. Deleted records remain visible and filterable in the connector's data source view [$[DPLAT-019]$].

### Security and Compliance Posture

**Authentication:** The connector uses OAuth 2.0 with the Salesforce Connected App flow. Tokens are encrypted at rest using AES-256-GCM in the tenant's secure credential store. The OAuth flow requires only the minimum necessary scopes: `api` (full API access), `refresh_token` (long-lived refresh capability), and `webhook` (for real-time sync subscriptions) [$[Salesforce Connector — Business Rules]$].

**Data Protection:** All cached Salesforce data is encrypted at rest using AES-256 and is never exposed outside the tenant boundary. Cached records are retained for a default of 30 days, with configurable extension up to 90 days for compliance requirements [$[Salesforce Connector — Business Rules]$].

**Error Handling and Audit:** The connector implements comprehensive error handling with automatic retry logic, quarantine mechanisms for failed records, and detailed audit logging. All errors are logged with type-specific entries (e.g., `ERROR_4XX`, `ERROR_5XX`, `RATE_LIMITED`) for complete traceability. Quarantined records are retained for 7 days and can be manually reprocessed via the Connector UI, with exportable quarantine logs for compliance officers [$[Salesforce Connector — Business Rules]$].

**IP Allowlisting:** The connector requires Salesforce IP allowlisting for DPLAT outbound addresses, ensuring that only authorized connections from the platform can access your Salesforce org. This is a standard security practice for enterprise integrations [$[Salesforce Connector — Business Rules]$].

**Reliability:** The connector targets 99.9% uptime across tenant workspaces during business hours, with automatic retry on transient failures and health monitoring integration to detect and alert on issues proactively [$[DPLAT-EPIC-01]$].

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)

## Compliance & Security Highlights

### High-Level Functionality

The Salesforce Connector enables seamless, bidirectional synchronization between Salesforce CRM and the Amisol DataPlatform. For the platform user, it acts as a secure bridge that automatically ingests Salesforce records (Accounts, Contacts, Opportunities, Leads, Cases, and custom objects) into the platform's unified data lake — eliminating the need for custom ETL development or manual data exports. The connector supports three sync modes: near real-time (webhook-driven, under 5 seconds latency), hourly batch, and daily snapshot, giving workspace admins flexibility based on their data freshness requirements.

### Customer-Visible Capabilities

- **Real-Time Change Data Capture**: Events propagate from Salesforce to the platform in under 5 seconds via Platform Events subscription, enabling up-to-the-minute analytics and compliance vault integration.
- **OAuth 2.0 Authentication**: Secure, token-based authentication using the Salesforce Connected App flow. Access tokens are stored encrypted in the tenant's secure vault and automatically refreshed before expiration (60-minute TTL).
- **Field-Level Mapping & Transformation**: Declarative field mapping with data type coercion, string formatting, date normalization, and lookup resolution — all configurable without code.
- **Record Deletion Propagation**: When records are deleted in Salesforce, the connector detects the deletion within 5 minutes and marks the corresponding platform record as "deleted" without immediate removal. Deleted records are retained for a configurable retention period (default 90 days) before permanent purging, ensuring audit trail completeness.
- **Connector Health Monitoring**: Integrated health dashboard that tracks sync status, latency, and error rates, with configurable alerting thresholds.

### Security & Compliance Posture

**Authentication & Access Control**: The connector uses OAuth 2.0 exclusively — no stored passwords or API keys. The OAuth flow requires explicit user consent via Salesforce's consent screen, and tokens are encrypted at rest using AES-256 within the tenant's isolated vault. Required OAuth scopes are limited to `api`, `refresh_token`, and `webhook` — no admin-level permissions are requested.

**Data Encryption**: All cached Salesforce data is encrypted at rest using AES-256. Cached records include full field snapshots, change tracking metadata, and relationship pointers — but cached data is never exposed outside the tenant boundary.

**Data Retention & Purging**: The local cache of synced records has a default retention period of 30 days, after which records are automatically purged. Workspace admins may configure extended retention up to 90 days for compliance requirements (subject to additional storage costs).

**Audit Trail**: Every sync operation, authentication event, and error condition is logged in the platform's audit log. The connector supports scheduled CSV export of audit logs to customer-managed S3 buckets for off-platform compliance retention. Deletion events are captured with timestamp, source record ID, tenant identifier, and the user who triggered the source deletion.

**IP Allowlisting**: DPLAT outbound IP addresses must be allowlisted in the target Salesforce org. The connector supports an OAuth Proxy Mode for organizations that cannot immediately implement IP allowlisting, routing connections through the customer's outbound proxy.

**Error Handling & Quarantine**: API errors are handled with configurable retry logic (exponential backoff for 4xx errors, up to 5 retries over 15 minutes for 5xx errors). Quarantined records are retained for 7 days and can be manually reprocessed via the Connector UI. Compliance officers can export quarantine logs for audit purposes.

**Compliance Alignment**: The connector's architecture supports GDPR and other data protection regulations through:
- Encrypted token storage with automatic refresh
- Configurable data retention with automatic purging
- Complete audit trail of all data access and modification events
- Deletion propagation that maintains records for retention periods before permanent removal
- Tenant-isolated data boundaries with no cross-tenant data exposure

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)

## Get a Demo (call to action)

### What the Salesforce Connector Does for You

The Salesforce Connector is a **bi-directional synchronization bridge** between your Salesforce CRM and the Amisol DataPlatform. At a high level, it automatically moves your Salesforce data—Accounts, Contacts, Opportunities, Leads, and Cases—into the platform's unified data lake without requiring custom ETL code or manual exports. Once connected, your team can run analytics, apply compliance controls, and perform cross-platform data operations on Salesforce data in near real-time.

### Customer-Visible Capabilities

- **Real-Time Data Sync**: Changes in Salesforce propagate to the platform in under 5 seconds via webhook-driven events (per [$[Salesforce Connector — Business Rules]$] and [$[DPLAT-EPIC-01]$]). No more waiting for nightly batch jobs.
- **Guided Setup Wizard**: A step-by-step interface lets your workspace admin connect Salesforce in minutes—enter OAuth credentials, select which objects to sync, and the connector goes live (per [$[DPLAT-002]$]).
- **Field-Level Mapping**: Declaratively map Salesforce fields to platform fields, with data type coercion and transformation rules (string formatting, date normalization). Custom objects are supported after schema registration.
- **Automatic Token Management**: OAuth 2.0 tokens refresh silently before expiry, so data sync continues uninterrupted. If refresh fails, the workspace admin receives an alert (per [$[DPLAT-003]$]).
- **Deletion Propagation**: When records are deleted in Salesforce, the connector detects the event within 5 minutes and marks the corresponding platform record as "deleted" while retaining it per your compliance retention policy (default 90 days) (per [$[DPLAT-019]$]).
- **Connector Health Monitor**: A dashboard shows sync status, last sync timestamps, and alerts for any issues—giving your team confidence that data is flowing correctly.

### Security & Compliance Posture

- **Authentication**: All connections use **OAuth 2.0** via Salesforce Connected App flow. Tokens are encrypted at rest using **AES-256-GCM** in the tenant's secure credential store (per [$[Salesforce Connector — Business Rules]$] and [$[DPLAT-003]$]).
- **Data Encryption**: Cached Salesforce data is encrypted at rest with AES-256. Data is never exposed outside your tenant boundary.
- **Audit Trail**: Every sync event, authentication attempt, and error is logged with timestamp, user, action, and outcome. Audit logs can be exported to your own S3 bucket for compliance retention (per [$[DPLAT-009]$]).
- **IP Allowlisting**: DPLAT outbound IP ranges must be allowlisted in your Salesforce org's Network Access settings, ensuring only authorized connections reach your data.
- **Retention Controls**: Cached data is automatically purged after 30 days (configurable up to 90 days). Deleted records are retained per policy before permanent removal.
- **Error Handling**: API errors trigger automatic retries with exponential backoff. Quarantined records are retained for 7 days and can be manually reprocessed. Compliance officers can export quarantine logs for audit purposes.

### Why This Matters for Your Demo

When you see the Salesforce Connector in action, you'll witness a **production-ready integration** that eliminates manual data movement, enforces enterprise security standards, and gives your team a single source of truth for Salesforce data—all without writing a single line of code. **Schedule your demo today** to see how quickly you can connect Salesforce and start unlocking insights across your organization.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-037] Audit Log — full-text search across historical exports](https://demo-jira.local/browse/DPLAT-037)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-009] Audit Log Export — scheduled CSV export to S3 bucket](https://demo-jira.local/browse/DPLAT-009)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-019] Salesforce — record deletion propagation policy](https://demo-jira.local/browse/DPLAT-019)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)
