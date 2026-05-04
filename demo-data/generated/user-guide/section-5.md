# 5  FAQ

> Quick answers to frequent questions

## General Questions

Based on the available documentation, here are the most common general questions and answers regarding the DataPlatform (DPLAT) system:

### Frequently Asked Questions

**Q: What is the Compliance Vault and what does it do?**
A: The Compliance Vault (MOD-B) is the privacy and governance layer of DataPlatform. It enables tenants to identify, classify, and track access to sensitive data across all connected data sources, ensuring alignment with regulatory requirements such as GDPR and the German BDSG. It features PII Auto-Tagging (F-B1) and Audit Log Export (F-B2) capabilities. [CONFLUENCE] [$[Compliance Vault — Module Overview]$]

**Q: How does PII detection work?**
A: The PII Auto-Tagging engine scans column values using pattern-matching rules, applies machine-learning classifiers for probabilistic detection, tags identified fields with standardized PII categories (email, phone, national ID, name, address, IP address), and propagates tags to downstream reports and dashboards. [CONFLUENCE] [$[Compliance Vault — Module Overview]$]

**Q: What connectors are available?**
A: The Connector Framework supports multiple data source integrations. For example, the Salesforce Connector enables bi-directional synchronization between Salesforce orgs and DPLAT workspaces, supporting objects like Account, Contact, Lead, Opportunity, Case, and Custom Objects. [CONFLUENCE] [$[Salesforce Connector — Business Rules]$]

**Q: How are audit logs queried?**
A: The Compliance Vault exposes a domain-specific query language (DSL) for filtering and aggregating audit log events. Queries support filtering by event type, timestamp range, actor identity, resource path, and custom metadata. They can be submitted via the `/api/v1/compliance/audit-query` endpoint or through the Compliance Vault UI. [CONFLUENCE] [$[Audit Log — Query Language Reference]$]

### How to Contact Support

For technical issues or escalation, use the severity-based support system:

| Severity | Description | Response SLA |
|----------|-------------|--------------|
| SEV-1 | Complete outage, data loss, or PII exposure | 1 hour, 24/7 |
| SEV-2 | Major feature broken, no workaround | 4 business hours |
| SEV-3 | Minor functionality impacted, workaround exists | 1 business day |
| SEV-4 | General questions, feature requests | 2 business days |

SEV-1 incidents require immediate page to the on-call engineer via PagerDuty. For persistent connector issues, gather the connector version, tenant ID, last successful sync timestamp, and relevant audit log entries (with PII redacted) before contacting support. [CONFLUENCE] [$[Customer Success — Internal FAQ]$], [$[Salesforce Connector — Troubleshooting Guide]$]

### System Limitations

Key system limitations include:

- **Audit Query Limits**: Maximum 100,000 events per query; regex matches limited to 100-byte patterns; aggregations capped at 1,000 distinct groups; queries older than tenant retention policy return empty results. [CONFLUENCE] [$[Audit Log — Query Language Reference]$]

- **PII Classifier**: Maximum request body size of 1,048,576 bytes (1 MB); minimum confidence threshold of 0.8 to flag as PII. [GITHUB] [$[pii-classifier-service — README]$]

- **Salesforce Connector**: Cached data retention defaults to 30 days (configurable up to 90 days); requires IP allowlisting of DPLAT outbound addresses; supports up to 5 retry attempts with exponential backoff before entering FAILED state. [CONFLUENCE] [$[Salesforce Connector — Business Rules]$], [$[Salesforce Connector — Troubleshooting Guide]$]

- **Connector Framework**: Each tenant has an isolated worker pool with configurable resource limits; parallelization respects the `max_concurrent_streams` setting per connector. [CONFLUENCE] [$[Connector Framework — Architecture Deep-Dive]$]

For billing or account-related questions, refer to the pricing and account management sections of the internal FAQ.

**Sources:**
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-REQ-12] Salesforce — respect upstream API rate limits with adaptive backoff](https://demo-jira.local/browse/DPLAT-REQ-12)
- 📋 [[DPLAT-REQ-16] PII — model inference must run within tenant geo-region](https://demo-jira.local/browse/DPLAT-REQ-16)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)

## Feature Specific FAQ

### Frequently Asked Questions

**Q: How does PII auto-detection work in the Compliance Vault?**
A: The PII Classifier Service uses a hybrid detection model combining deterministic regex pattern matching with machine learning classification. Rule-based detection handles known formats like emails, SSNs, and phone numbers, while ML models identify names, addresses, and other sensitive entities. Each detection receives a confidence score (0.0–1.0), with tagging occurring above a 0.75 threshold. The service supports English, German, and French at launch, with unsupported languages falling back to English models at reduced confidence. Classification happens synchronously during the ingestion pipeline, ensuring PII is identified before any downstream processing [$[PII Auto-Tagging — Policy and Behavior]$].

**Q: What is the default retention period for PII-tagged data?**
A: The platform-wide default retention period is **30 days**, after which data is automatically anonymized or deleted according to the configured retention policy. Per-tenant overrides are available through the tenant configuration API, and workspace admins may request extended retention by submitting a compliance review via DPLAT-006 [$[PII Auto-Tagging — Policy and Behavior]$].

**Q: How can I query audit log events?**
A: The Compliance Vault provides a domain-specific query language (DSL) for filtering and aggregating audit log events. Queries are submitted via the `/api/v1/compliance/audit-query` endpoint or through the Compliance Vault UI. You can filter by event type, timestamp range (absolute ISO-8601 or relative like `-30d`), actor identity, resource path, and custom metadata. Aggregations like `count BY actor_role` or `SUM(bytes_transferred) BY event_type` are supported [$[Audit Log — Query Language Reference]$].

**Q: What are the limitations of the audit log query system?**
A: The system has the following constraints: maximum 100,000 events per query, regex matches limited to 100-byte patterns, aggregations capped at 1,000 distinct groups, and queries older than the tenant retention policy return empty results [$[Audit Log — Query Language Reference]$].

### How to Contact Support

For critical production issues, use the severity escalation matrix:
- **SEV-1** (complete outage, data loss, or PII exposure): 1-hour response SLA, 24/7 — requires immediate page to on-call engineer via PagerDuty
- **SEV-2** (major feature broken): 4 business hours
- **SEV-3** (minor functionality impacted): 1 business day
- **SEV-4** (general questions, feature requests): 2 business days

For Professional Services engagement (custom connector development, complex data mapping, on-premises deployments), CS can book an initial discovery call at no cost, with a separate statement of work required for actual engagement [$[Customer Success — Internal FAQ]$].

### System Limitations

- **Audit Log Query**: Maximum 100,000 events per query; regex patterns limited to 100 bytes; aggregations capped at 1,000 distinct groups [$[Audit Log — Query Language Reference]$]
- **Salesforce Connector**: Attachments larger than **5MB** are silently dropped during sync — this is a known bug (DPLAT-DEF-09, currently Open) with no error logged [$[DPLAT-DEF-09]$]
- **PII Detection**: Only English, German, and French are fully supported at launch; unsupported languages use English models as fallback with reduced confidence thresholds [$[PII Auto-Tagging — Policy and Behavior]$]
- **Storage Backend**: Postgres is used for v2 audit log storage; aggregation queries over 6+ months will be slow without materialized views, and storage costs are 3-4x higher than ClickHouse at equivalent retention [$[ADR-007 — Storage Backend for Audit Log]$]
- **Connector Retry**: After five failed attempts with exponential backoff, connectors enter `FAILED` state and require manual intervention [$[Connector Framework — Architecture Deep-Dive]$]

**Sources:**
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-REQ-12] Salesforce — respect upstream API rate limits with adaptive backoff](https://demo-jira.local/browse/DPLAT-REQ-12)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-REQ-16] PII — model inference must run within tenant geo-region](https://demo-jira.local/browse/DPLAT-REQ-16)

## Security FAQ

### Frequently Asked Questions

**Q: How does the system protect sensitive data?**
A: The DataPlatform employs multiple security layers. All connector-to-data-source communication uses TLS 1.3 with mutual authentication and certificate pinning for production connectors ([CONFLUENCE] Connector Framework — Architecture Deep-Dive). The PII Auto-Tagging feature (F-B1) automatically identifies and classifies personally identifiable information at ingestion time using a hybrid rule+ML detection engine, supporting English, German, and French ([CONFLUENCE] PII Auto-Tagging — Policy and Behavior). PII-tagged data is subject to strict data residency controls under GDPR Art. 44 and BDSG, with region-aware routing ensuring data never leaves its designated region without explicit consent ([CONFLUENCE] Compliance Vault — Module Overview).

**Q: How are credentials and secrets managed?**
A: Connector credentials are never stored in plaintext. The Secret Vault provides encryption at rest using AES-256-GCM with per-tenant encryption keys and just-in-time decryption with automatic revocation ([CONFLUENCE] Connector Framework — Architecture Deep-Dive).

**Q: What is the PII data retention policy?**
A: The platform-wide default retention period for PII-tagged data is **30 days**, after which data is automatically anonymized or deleted according to the configured retention policy. Per-tenant overrides are available through the tenant configuration API with compliance officer approval ([CONFLUENCE] PII Auto-Tagging — Policy and Behavior).

**Q: Who can export audit logs?**
A: Only users with the **Compliance Officer** role can trigger audit log exports. This RBAC requirement is enforced by the system ([JIRA] DPLAT-REQ-10). Exported files are encrypted at rest using AES-256 and in transit using TLS 1.3, with all authorization decisions logged to the immutable audit trail.

**Q: How are security incidents escalated?**
A: For SEV-1 incidents (complete outage, data loss, or PII exposure), the response SLA is 1 hour with 24/7 on-call engineer paging via PagerDuty. CS must stay engaged until resolution confirmation ([CONFLUENCE] Customer Success — Internal FAQ).

### How to Contact Support

For security-related issues, use the severity matrix:
- **SEV-1** (complete outage, data loss, PII exposure): Immediate page to on-call engineer via PagerDuty, 1-hour response SLA, 24/7
- **SEV-2** (major feature broken, no workaround): 4 business hours response
- **SEV-3** (minor functionality impacted): 1 business day
- **SEV-4** (general questions): 2 business days

For connector-specific issues, gather the connector version, tenant ID, last successful sync timestamp, and relevant audit log entries (with PII redacted) before contacting support ([CONFLUENCE] Salesforce Connector — Troubleshooting Guide).

### System Limitations

- **Audit log queries**: Maximum 100,000 events per query; regex matches limited to 100-byte patterns; aggregations capped at 1,000 distinct groups ([CONFLUENCE] Audit Log — Query Language Reference)
- **PII detection**: Data in unsupported languages is processed with English models as fallback with reduced confidence thresholds ([CONFLUENCE] PII Auto-Tagging — Policy and Behavior)
- **Connector sync**: Maximum payload size for the PII Classifier Service is 1,048,576 bytes (1 MB); exponential backoff with jitter applies after 5 failed attempts, after which the connector enters FAILED state ([GITHUB] pii-classifier-service README; [CONFLUENCE] Connector Framework — Architecture Deep-Dive)
- **Export performance**: Audit log export must complete within 30 seconds for datasets up to 100,000 entries; supports up to 5 concurrent compliance officers without degradation ([JIRA] DPLAT-REQ-10)

**Sources:**
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-REQ-16] PII — model inference must run within tenant geo-region](https://demo-jira.local/browse/DPLAT-REQ-16)
- 📋 [[DPLAT-REQ-12] Salesforce — respect upstream API rate limits with adaptive backoff](https://demo-jira.local/browse/DPLAT-REQ-12)

## Troubleshooting (common)

# FAQ — Troubleshooting (Common)

## Frequently Asked Questions (Troubleshooting)

Based on the available documentation, here are the most common troubleshooting scenarios and their resolutions:

### Salesforce Connector Issues

**Q: The setup wizard fails with "Connection timeout" or "Access denied from IP" errors.**
A: This is typically caused by DPLAT outbound IP addresses not being whitelisted in your Salesforce organization's **Network Access** settings. Per [$[Salesforce Connector — Troubleshooting Guide]$], you must add the DPLAT IP ranges (`203.0.113.0/24` for US-East, `198.51.100.0/24` for EU-West) to **Setup → Security → Network Access** in Salesforce. If IP whitelisting isn't immediately possible, use **OAuth Proxy Mode** as a workaround.

**Q: OAuth token refresh fails with intermittent `401 Unauthorized` errors.**
A: This occurs when the connector's background token refresh mechanism fails. Common causes include expired refresh tokens (`invalid_grant`), client credential mismatches (`invalid_client`), or rate limiting. Resolution: Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens. Enable **Token Refresh Alerting** to receive proactive notifications.

**Q: Object sync shows stale data with no errors logged.**
A: Sync delays typically stem from Salesforce API rate limits, large object volumes (>100K records), complex custom SOQL queries, or active retention policies adding processing overhead. Enable incremental sync for large objects, simplify custom queries, and adjust sync frequency. Use **Staged Sync** mode to prioritize critical objects (Accounts, Opportunities) separately from archival data.

**Q: The Health Monitor shows "Degraded" status but data queries return expected results.**
A: This is often a false positive caused by latency thresholds (>2s response time), partial object failures, or metadata polling issues. Review **Health Monitor Details** to identify the specific failing metric, adjust sensitivity thresholds in **Connector → Health Settings**, and exclude non-critical objects from monitoring. Create a custom **Health Check Query** for more accurate compliance reporting.

## How to Contact Support

For issues that persist after applying the troubleshooting steps above, gather the following information before contacting support:
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (with PII redacted)
- Salesforce org ID (first 10 characters)

Include reference to **DPLAT-DEF-02** when reporting IP allowlist-related issues.

For critical production issues, use the severity escalation matrix:
- **SEV-1** (complete outage, data loss, or PII exposure): 1-hour response SLA, 24/7 — page the on-call engineer via PagerDuty
- **SEV-2** (major feature broken, no workaround): 4 business hours
- **SEV-3** (minor functionality impacted, workaround exists): 1 business day
- **SEV-4** (general questions, feature requests): 2 business days

## System Limitations

Based on the available documentation:

**Audit Log Query Limitations** (per [$[Audit Log — Query Language Reference]$]):
- Maximum 100,000 events per query
- Regex matches limited to 100-byte patterns
- Aggregations capped at 1,000 distinct groups
- Queries older than tenant retention policy return empty results

**Salesforce Connector Limitations** (per [$[Salesforce Connector — Business Rules]$]):
- Delete operations are not supported for any standard or custom objects
- Custom objects require explicit schema registration before sync
- Cached data retention defaults to 30 days (up to 90 days with additional storage costs)
- Near real-time sync (webhook-driven) requires Salesforce Enterprise or Unlimited editions
- Quarantined records are retained for only 7 days

**Connector Framework Error Handling** (per [$[Connector Framework — Architecture Deep-Dive]$]):
- After five failed retry attempts (with exponential backoff), the connector enters `FAILED` state
- Permanent errors (schema mismatch, invalid credentials) fail immediately without retry
- Each tenant has an isolated worker pool with configurable resource limits

**Sources:**
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-REQ-02] Connector framework rate-limiting — fairness across tenants](https://demo-jira.local/browse/DPLAT-REQ-02)
- 📋 [[DPLAT-REQ-14] Health Monitor — 1s p99 read latency for status API](https://demo-jira.local/browse/DPLAT-REQ-14)
