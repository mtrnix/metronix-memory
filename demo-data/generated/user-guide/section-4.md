# 4  Common errors

> Resolving frequent user issues

## Connectivity Errors

### Why Is My Connection Failing?

Connection failures typically stem from one of three root causes, as documented in the [$[Salesforce Connector — Troubleshooting Guide]$]:

1. **IP Allowlist Restrictions**: The DPLAT connector's outbound IP addresses must be whitelisted in your Salesforce organization's **Network Access** settings. If these IP ranges are not added to Salesforce Trusted IP Ranges, the connection test will fail with errors like `Connection timeout` or `Access denied from IP: X.X.X.X`. This is documented in DPLAT-DEF-02.

2. **OAuth Credential Issues**: Expired or revoked OAuth tokens cause `401 Unauthorized` errors with messages like `OAuth token refresh failed`. Common error codes include:
   - `invalid_grant` — Refresh token expired or revoked
   - `invalid_client` — Client credentials mismatch
   - `rate_limit_exceeded` — Too many refresh attempts

3. **Network/Firewall Blocks**: Corporate firewalls may block outbound connections to DPLAT endpoints. Verify your tenant's outbound firewall allows connections to DPLAT endpoints.

**Resolution Steps** (per the Troubleshooting Guide):
- Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
- Verify OAuth credentials are valid and not expired
- Confirm your tenant's outbound firewall allows connections to DPLAT endpoints
- Re-run the connection test in the setup wizard

**Workaround**: If IP whitelisting is not immediately possible, use **OAuth Proxy Mode** which routes connections through your organization's outbound proxy.

### How to Fix Tagging Errors?

Tagging errors in the context of connectivity are addressed through the **retry queue mechanism** described in [$[DPLAT-018]$]. The Salesforce connector automatically retries failed sync operations using a configurable retry queue with exponential backoff (max 5 attempts, 30-minute window) for transient Salesforce API errors (HTTP 429, 503). Records that fail all retry attempts are moved to a dead-letter queue with full error context, allowing workspace admins to view, filter, and manually reprocess them.

### Common Error Code Meanings

| Error Code | Meaning | Source |
|------------|---------|--------|
| `Connection timeout` | DPLAT IP ranges not whitelisted in Salesforce, or network/firewall blocking outbound connections | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `Access denied from IP: X.X.X.X` | Salesforce IP allowlist restriction blocking the connector's outbound IP | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `invalid_grant` | OAuth refresh token expired or revoked | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `invalid_client` | Client credentials mismatch | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `rate_limit_exceeded` | Too many OAuth refresh attempts | [$[Salesforce Connector — Troubleshooting Guide]$] |
| HTTP 429, 503 | Transient Salesforce API errors (automatically retried via retry queue) | [$[DPLAT-018]$] |
| HTTP 5xx | Critical sync failure (triggers PagerDuty and email alerts per [$[DPLAT-008]$]) | [$[DPLAT-008]$] |
| HTTP 4xx | Warning-level sync failure | [$[DPLAT-008]$] |

**Important Note**: Per [$[DPLAT-DEF-02]$], the setup wizard may show a green checkmark even when IP allowlist restrictions exist, causing silent failures during subsequent sync jobs. Always verify IP allowlist configuration before completing setup.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)

## Permission Issues

`⚠ conflict` `⚠ stale`

The most common cause of connection failures in the Salesforce connector is **IP allowlist restrictions**. According to [$[Salesforce Connector — Troubleshooting Guide]$], the DPLAT connector requires outbound IP addresses to be whitelisted in your Salesforce organization's **Network Access** settings. If these IP ranges are not added, you will encounter errors such as `Connection timeout` or `Access denied from IP: X.X.X.X` during the connection test.

A specific bug, [$[DPLAT-DEF-02]$], highlights a critical UX issue: when connecting to a sandbox org with a restricted IP allowlist, the setup wizard may show a green checkmark indicating success, but subsequent data sync jobs fail with generic "connection timeout" errors. This silent failure can waste hours of troubleshooting time.

### How to Fix Tagging Errors

Tagging errors in the context of permission issues are primarily related to **PII tagging** and **retention policy** misconfigurations. The [$[PII Tagging — Initial Design (Legacy)]$] document explains that PII tagging operates post-ingestion and relies on regex-based pattern matching. However, two known bugs affect tagging reliability:

1. **[$[DPLAT-DEF-07]$]**: When importing CSV files, the PII auto-tagging feature only scans the first 100 rows. Email addresses in rows 101+ are not detected or tagged. The workaround is to split large CSV files into chunks of 100 rows or fewer before import, or manually tag the "user_email" column as PII before importing.

2. **[$[DPLAT-DEF-04]$]**: The default retention period for cached connector data is **90 days**, not the documented **30 days**. This discrepancy can cause compliance issues. The workaround is to manually configure the retention period to 30 days in each connector's settings after creation.

### Common Error Code Meanings

Based on the [$[Salesforce Connector — Troubleshooting Guide]$], here are the key error codes for permission-related issues:

| Error Code | Meaning |
|------------|---------|
| `invalid_grant` | Refresh token expired or revoked |
| `invalid_client` | Client credentials mismatch |
| `rate_limit_exceeded` | Too many refresh attempts |
| `CONNECTION_TIMEOUT` | Network connectivity issue (often IP allowlist related) |

For **OAuth Token Refresh Errors**, the connector logs may show intermittent `401 Unauthorized` errors with the message `OAuth token refresh failed`. Resolution involves re-authenticating via **Connectors → Salesforce → Settings → Re-authenticate** and verifying the Salesforce Connected App is still active.

### Summary of Resolution Steps

1. **IP Allowlist**: Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**. If IP whitelisting is not immediately possible, use **OAuth Proxy Mode** which routes connections through your organization's outbound proxy.

2. **OAuth Credentials**: Verify OAuth credentials are valid and not expired. Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new tokens.

3. **Network Connectivity**: Confirm your tenant's outbound firewall allows connections to DPLAT endpoints.

4. **Retention Configuration**: Manually set the retention period to 30 days in each connector's settings to align with documented policies.

5. **CSV Tagging**: For large CSV imports, split files into chunks under 100 rows or manually tag PII columns before import.

**Sources:**
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)

## Data Format Errors

### Why Is My Connection Failing?

Based on the troubleshooting documentation, connection failures related to data format errors are primarily caused by **PII tagging pipeline issues** that affect data ingestion and processing. According to [CONFLUENCE] [$[Salesforce Connector — Troubleshooting Guide]$], connection failures during setup typically manifest as `Connection timeout` or `Access denied from IP` errors, but these are network/credential issues rather than data format problems.

However, data format errors can cause connection failures indirectly through the **PII classification pipeline**. Per [JIRA] [$[DPLAT-DEF-16]$], the PII classifier crashes with an `OutOfMemoryError` (HTTP 500) when processing documents larger than 1MB. This crash can make the connector appear to fail because the classification job fails completely without returning partial results. The root cause is that the classifier loads the entire document into memory before processing, rather than streaming it in chunks.

Additionally, [JIRA] [$[DPLAT-DEF-07]$] reveals that CSV imports with email addresses only scan the first 100 rows for PII tagging, leaving rows 101+ untagged. This is caused by a hardcoded buffer size limit in the CSV parsing logic, which can lead to undetected PII and downstream compliance violations.

### How to Fix Tagging Errors

To resolve PII tagging errors related to data format issues:

1. **For large documents (>1MB)**: Split documents into chunks under 1MB before uploading, or use the "Quick Scan" mode which has different memory behavior (per [$[DPLAT-DEF-16]$]).

2. **For CSV imports**: Manually split large CSV files into chunks of 100 rows or fewer before import, then merge results post-import. Alternatively, manually tag the "user_email" column as PII before importing to force classification on all rows (per [$[DPLAT-DEF-07]$]).

3. **For SAP CHAR fields with German umlauts**: Preprocess source data in SAP to replace umlauts with ASCII equivalents (ae, oe, ue, ss) before extraction, or apply post-processing transformation to restore characters based on known mappings (per [$[DPLAT-DEF-11]$]).

4. **For Salesforce attachments >5MB**: Manually compress attachments to under 5MB before syncing, or use Salesforce's API directly to transfer large files separately (per [$[DPLAT-DEF-09]$]).

### Common Error Code Meanings for Data Format Errors

Based on the troubleshooting guide and Jira issues:

| Error Code/Behavior | Meaning | Source |
|---------------------|---------|--------|
| `OutOfMemoryError` (HTTP 500) | Document exceeds 1MB; classifier loads entire file into memory | [$[DPLAT-DEF-16]$] |
| PII tagging skips rows 101+ | Hardcoded buffer size limit in CSV parser (100 rows) | [$[DPLAT-DEF-07]$] |
| Null values for German umlauts | Encoding mismatch in SAP CHAR field extraction | [$[DPLAT-DEF-11]$] |
| Silent attachment drop (>5MB) | Hardcoded size limit in Salesforce connector; no error logged | [$[DPLAT-DEF-09]$] |
| `invalid_grant` | OAuth refresh token expired or revoked | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `invalid_client` | Client credentials mismatch | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `rate_limit_exceeded` | Too many OAuth refresh attempts | [$[Salesforce Connector — Troubleshooting Guide]$] |

### Key Takeaway

Data format errors in the connector ecosystem are **silent and insidious**—they often don't produce clear error messages. The PII tagging pipeline has known limitations with file size (1MB limit) and CSV row count (100-row scan limit), while the Salesforce connector silently drops attachments over 5MB. The SAP connector returns null for German umlauts without warning. These issues require proactive workarounds until permanent fixes are implemented (e.g., streaming for large documents, removing hardcoded buffer limits).

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)

## Sync Failures

`⚠ conflict` `⚠ stale`

### Primary Question: Why is my connection failing?

Connection failures during Salesforce sync typically stem from three main causes, per the [$[Salesforce Connector — Troubleshooting Guide]$]:

1. **IP Allowlist Restrictions**: The most common cause is that DPLAT's outbound IP ranges haven't been added to your Salesforce organization's **Network Access** settings. This is documented in DPLAT-DEF-02. The setup wizard may show a false success, but subsequent sync jobs fail with "connection timeout" errors (based on [$[DPLAT-DEF-02]$]).

2. **OAuth Token Issues**: Intermittent `401 Unauthorized` errors with "OAuth token refresh failed" indicate expired or revoked refresh tokens. Common error codes include:
   - `invalid_grant` — Refresh token expired or revoked
   - `invalid_client` — Client credentials mismatch
   - `rate_limit_exceeded` — Too many refresh attempts

3. **Salesforce-Side Outages**: After a Salesforce outage, the connector recovery process currently takes approximately **4 hours** instead of the expected 30-60 minute SLA, as documented in [$[DPLAT-DEF-15]$]. A manual connector restart reduces this to ~15 minutes.

**Resolution Steps**:
- Contact your Salesforce admin to add DPLAT IP ranges to **Setup → Security → Network Access**
- Re-authenticate via **Connectors → Salesforce → Settings → Re-authenticate**
- For IP issues, use **OAuth Proxy Mode** as a workaround

### How to Fix Tagging Errors?

Tagging errors in the context of sync failures relate to the PII tagging pipeline described in [$[PII Tagging — Initial Design (Legacy)]$]. The tagging system operates **post-ingestion** and uses regex-based pattern matching. Common issues:

- **False Positives**: Regex patterns may match version numbers as SSNs or other non-PII data. The system has no context-aware detection.
- **Language Limitations**: Only English-language data is supported. Non-English sources require manual compliance officer review.
- **Retention Conflicts**: Tagged PII automatically inherits retention rules (e.g., SSN/CC = 2 years, Email/Phone = 5 years). If sync failures cause data staleness, retention policies may trigger violations.

**Fixes**:
- Workspace admins can override redaction defaults per PII type via the UI
- Add custom regex patterns to reduce false positives
- For sync-related tagging failures, ensure the connector is healthy first, then re-run the tagging pipeline

### Common Error Code Meanings

| Error Code | Meaning | Source |
|------------|---------|--------|
| `Connection timeout` | IP not whitelisted or firewall blocking | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `Access denied from IP: X.X.X.X` | IP allowlist restriction in Salesforce | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `invalid_grant` | OAuth refresh token expired or revoked | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `invalid_client` | Client credentials mismatch | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `rate_limit_exceeded` | Too many OAuth refresh attempts | [$[Salesforce Connector — Troubleshooting Guide]$] |
| HTTP 429 / 503 | Transient Salesforce API errors (automatically retried up to 5 times with exponential backoff) | [$[DPLAT-018]$] |
| HTTP 5xx | Critical sync failure — triggers PagerDuty alert | [$[DPLAT-008]$] |
| HTTP 4xx | Warning-level sync failure | [$[DPLAT-008]$] |
| Silent failure (no error logged) | Attachments >5MB dropped during sync | [$[DPLAT-DEF-09]$] |

**Important Note**: The bug [$[DPLAT-DEF-09]$] reports that attachments larger than 5MB are silently dropped with no error logged. This is a known defect (status: Open) that causes data loss without any error indication. The workaround is to manually compress attachments or use Salesforce's API directly.

**Sources:**
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)

## Troubleshooting (common)

### Why Is My Connection Failing?

Connection failures typically stem from one of three root causes, as documented in the [$[Salesforce Connector — Troubleshooting Guide]$]:

**1. IP Allowlist Restrictions** — The most common cause. The DPLAT connector requires outbound IP addresses to be whitelisted in your Salesforce organization's **Network Access** settings. If your Salesforce org (especially sandbox environments) has a restricted IP allowlist that doesn't include the DPLAT IP ranges, the connection test may appear to succeed in the setup wizard but subsequent data sync jobs will fail with generic "connection timeout" errors. This is a known issue tracked in [$[DPLAT-DEF-02]$], where the setup wizard fails silently without warning users about this prerequisite.

**Resolution**: Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**. Reference DPLAT-DEF-02 when reporting IP allowlist-related issues.

**2. OAuth Credential Issues** — Expired or revoked OAuth tokens cause `401 Unauthorized` errors with messages like `OAuth token refresh failed`. The connector's background token refresh mechanism may fail if the Salesforce Connected App has been deleted or if refresh tokens have expired.

**Resolution**: Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens. Verify the Salesforce Connected App still exists and is active.

**3. Network/Firewall Blocking** — Corporate firewalls may block outbound connections to DPLAT endpoints. Confirm your tenant's outbound firewall allows connections to DPLAT endpoints.

**Workaround**: If IP whitelisting is not immediately possible, use **OAuth Proxy Mode** which routes connections through your organization's outbound proxy (requires coordination with your network team).

### How to Fix Tagging Errors?

Tagging errors primarily relate to PII (Personally Identifiable Information) detection and classification. Two known issues exist:

**1. CSV Import Scanning Limit** — Per [$[DPLAT-DEF-07]$], when importing CSV files, the PII auto-tagging feature only scans the first **100 rows**. Email addresses and other PII in rows 101+ are not detected or tagged. This is a high-severity bug that could result in undetected PII being stored without proper encryption or access controls, potentially violating GDPR/CCPA requirements.

**Workaround**: Manually split large CSV files into chunks of 100 rows or fewer before import, then merge results post-import. Alternatively, manually tag the "user_email" column as PII before importing to force classification on all rows.

**2. Large Document Crashes** — Per [$[DPLAT-DEF-16]$], the PII classifier crashes with an `OutOfMemoryError` on documents larger than 1MB. The service returns HTTP 500 with no partial results and exposes internal stack traces (a security concern).

**Workaround**: Split large documents into chunks under 1MB before uploading. Alternatively, use the "Quick Scan" mode which appears to have different memory behavior (though less thorough).

### Common Error Code Meanings

Based on the [$[Salesforce Connector — Troubleshooting Guide]$] and related sources:

| Error Code | Meaning | Source |
|------------|---------|--------|
| `Connection timeout` | DPLAT IP ranges not whitelisted in Salesforce; or corporate firewall blocking outbound connections | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `Access denied from IP: X.X.X.X` | Salesforce org's Network Access settings blocking the connector's IP | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `invalid_grant` | OAuth refresh token expired or revoked | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `invalid_client` | Client credentials mismatch (Salesforce Connected App issue) | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `rate_limit_exceeded` | Too many OAuth refresh attempts in a short period | [$[Salesforce Connector — Troubleshooting Guide]$] |
| `CONNECTION_TIMEOUT` (Health Monitor) | May be a **false positive** if the connector is intentionally paused — the Health Monitor incorrectly reports paused connectors as unhealthy (see [$[DPLAT-DEF-01]$]) | [$[DPLAT-DEF-01]$] |
| HTTP 429 / 503 (transient) | Salesforce API rate limiting or temporary unavailability — handled by the retry queue with exponential backoff (max 5 attempts, 30-minute window) per [$[DPLAT-018]$] | [$[DPLAT-018]$] |
| HTTP 5xx (sync failures) | Triggers "Critical" severity alerts in Health Monitor, with PagerDuty incident and email notification within 2 minutes (per [$[DPLAT-008]$]) | [$[DPLAT-008]$] |

### Additional Notes

- **Recovery Time**: After a Salesforce-side outage, automatic connector recovery takes approximately **4 hours** instead of the documented 30-60 minute target (see [$[DPLAT-DEF-15]$]). Manual restart of the connector service reduces recovery time to ~15 minutes.
- **Health Monitor False Positives**: The Health Monitor may show "Degraded" status even when data queries return expected results. Review **Health Monitor Details** to identify the specific failing metric, and consider creating a custom **Health Check Query** for business-critical data freshness validation.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
