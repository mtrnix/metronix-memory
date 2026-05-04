# 2.3  Troubleshooting connector failures

> Resolving connectivity and data sync issues.

## Error Identification

To identify why your connector failed, start by checking the **connector status** in the workspace admin console. A "Disconnected" or "Error" status indicates a connectivity failure, per the [$[Connector Operations Runbook]$]. The first step is to review the connector audit log for the last 100 events and verify data source credentials have not expired.

### Common Failure Symptoms and Root Causes

**1. Setup Wizard Fails (Connection Timeout / Access Denied)**
- **Symptom**: Connection test fails during initial configuration with `Connection timeout` or `Access denied from IP: X.X.X.X`.
- **Diagnosis**: The DPLAT connector requires outbound IP addresses to be whitelisted in your Salesforce organization's **Network Access** settings. Common causes include DPLAT IP ranges not added to Salesforce Trusted IP Ranges, corporate firewall blocking outbound connections, or incorrect/expired OAuth credentials. (Based on [$[Salesforce Connector — Troubleshooting Guide]$])

**2. OAuth Token Refresh Errors (401 Unauthorized)**
- **Symptom**: Intermittent `401 Unauthorized` errors with `OAuth token refresh failed`. Data sync stops until manually restarted.
- **Diagnosis**: The background token refresh mechanism encountered an issue. Error codes indicate specific causes:
  - `invalid_grant` — Refresh token expired or revoked
  - `invalid_client` — Client credentials mismatch
  - `rate_limit_exceeded` — Too many refresh attempts
  (Based on [$[Salesforce Connector — Troubleshooting Guide]$])

**3. Object Sync Delays (Stale Data, No Errors Logged)**
- **Symptom**: Objects show stale data; "Last Sync" timestamp is hours behind expected frequency, but no errors are logged.
- **Diagnosis**: Sync delays typically stem from API rate limits (Salesforce governor limits), large object volumes (>100K records requiring incremental sync), complex SOQL queries, or retention policy overhead. (Based on [$[Salesforce Connector — Troubleshooting Guide]$])

**4. Health Monitor False Positives (Degraded Status)**
- **Symptom**: Health Monitor shows "Degraded" but manual queries return expected results.
- **Diagnosis**: The health monitor evaluates multiple dimensions that may not reflect actual data availability — latency thresholds (>2s triggers warning), partial object failures, or metadata polling issues. (Based on [$[Salesforce Connector — Troubleshooting Guide]$])

**5. Known Connector Bugs (Error Identification)**
- **SAP connector sync hangs indefinitely** ([$[DPLAT-DEF-03]$]): When the SAP connector performs large OData syncs (>10,000 records), the paging cursor can expire, causing the connector to hang indefinitely with "Cursor validation in progress" messages. Memory usage grows during the hang.
- **Health Monitor false positive on paused connectors** ([$[DPLAT-DEF-01]$]): When a connector is intentionally paused, the Health Monitor incorrectly reports it as "Unhealthy" with `CONNECTION_TIMEOUT`, triggering false alerts.
- **Stale 'last sync' timestamp after restart** ([$[DPLAT-DEF-08]$]): After manual restart, the Health Monitor dashboard continues showing the pre-restart timestamp, even though the connector is syncing normally.
- **Alert deduplication merges unrelated incidents** ([$[DPLAT-DEF-14]$]): When multiple alerts trigger from different connectors within a short window, they are incorrectly merged into a single incident.

### How to Resolve Sync Errors

For **connectivity failures**, follow the runbook steps: check the connector health endpoint (`GET /api/v1/connectors/{id}/health`), review audit logs, verify credentials, and check network connectivity. If credentials expired, initiate rotation via the workspace admin console.

For **OAuth errors**, navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new tokens. Verify the Salesforce Connected App still exists and is active.

For **sync delays**, enable incremental sync for large objects, simplify custom queries, adjust sync frequency, and check if PII redaction rules are adding overhead.

For **known bugs**, apply the documented workarounds:
- SAP hang: Manually restart the connector and update the sync job to start from the last known checkpoint
- False positives: Manually disable health monitoring for paused connectors via `health_monitor.enabled=false`
- Stale timestamps: Refresh the browser or wait for the next automatic dashboard refresh cycle
- Merged incidents: Manually split merged incidents in the UI or increase the deduplication window

If issues persist, gather the connector version, tenant ID, last successful sync timestamp, relevant audit log entries (redact PII), and Salesforce org ID before contacting support.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Error Codes

### Why Did My Connector Fail?

Connector failures typically fall into three categories, each with specific error codes:

**1. OAuth Token Refresh Errors** (per [CONFLUENCE] [$[Salesforce Connector — Troubleshooting Guide]$])
| Error Code | Meaning |
|------------|---------|
| `invalid_grant` | Refresh token expired or revoked |
| `invalid_client` | Client credentials mismatch |
| `rate_limit_exceeded` | Too many refresh attempts |

These errors manifest as intermittent `401 Unauthorized` errors in connector logs, causing data sync to stop until manually restarted.

**2. Setup Wizard Failures** (per [CONFLUENCE] [$[Salesforce Connector — Troubleshooting Guide]$])
- `Connection timeout` — DPLAT IP ranges not whitelisted in Salesforce Trusted IP Ranges
- `Access denied from IP: X.X.X.X` — Corporate firewall blocking outbound connections

**3. Sync Failures** (per [JIRA] [$[DPLAT-008]$])
- HTTP `5xx` errors → Severity "Critical" — triggers PagerDuty and email alerts
- HTTP `4xx` errors → Severity "Warning"
- Timeout errors → Severity "Critical"

### How Do I Resolve Sync Errors?

**For OAuth errors:**
1. Navigate to **Connectors → Salesforce → Settings**
2. Click **Re-authenticate** to obtain new OAuth tokens
3. Verify the Salesforce Connected App still exists and is active
4. Check audit log for token revocation events

**For transient API errors (HTTP 429, 503):**
The system automatically retries with exponential backoff (max 5 attempts, 30-minute window) per [JIRA] [$[DPLAT-018]$]. Records that fail all retries move to a dead-letter queue for manual review.

**For setup wizard failures:**
1. Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
2. Verify OAuth credentials are valid
3. Confirm outbound firewall allows connections to DPLAT endpoints

**For sync delays:**
- Enable incremental sync for large objects (>100K records)
- Simplify custom SOQL queries
- Adjust sync frequency to comply with API limit tier

### What Are Known Connector Bugs?

| Bug | Error Code / Symptom | Status | Workaround |
|-----|---------------------|--------|------------|
| [$[DPLAT-DEF-01]$] — Health Monitor false positive on paused connectors | `CONNECTION_TIMEOUT` reported when connector is intentionally paused | **Open** | Set `health_monitor.enabled=false` (requires restart) |
| [$[DPLAT-DEF-02]$] — Salesforce setup wizard fails silently with restricted IP allowlist | No error shown; sync jobs fail with "connection timeout" | **Open** | Manually add DPLAT IP ranges to Salesforce Trusted IP Ranges before setup |
| [$[DPLAT-DEF-15]$] — Connector recovery takes ~4 hours after Salesforce outage | Recovery time 240 min vs. 60-min SLA / 30-min runbook target | **Open** | Manual restart reduces recovery to ~15 minutes |
| [$[DPLAT-DEF-03]$] — SAP connector hangs on OData paging cursor expiry | Sync hangs indefinitely; "Cursor validation in progress" in logs | **In Progress** | Restart connector and adjust sync start point; extend OData session timeout |

**Key takeaway:** For immediate resolution of most connector failures, check the specific error code against the tables above. The most common root cause is OAuth token expiry (`invalid_grant`) or IP allowlist misconfiguration (`Connection timeout`).

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-030] Connector recovery SLA — 60-minute target after upstream outage](https://demo-jira.local/browse/DPLAT-030)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Log Inspection

When investigating why your connector failed, the **Log Inspection** approach is your primary diagnostic tool. Here's how to use it effectively:

### Why Did My Connector Fail?

Based on the troubleshooting guide, connector failures typically manifest through specific log patterns:

1. **OAuth Token Refresh Errors** — Logs show intermittent `401 Unauthorized` errors with `OAuth token refresh failed` messages. This indicates expired or revoked refresh tokens, client credential mismatches, or rate-limited refresh attempts [$[Salesforce Connector — Troubleshooting Guide]$].

2. **Setup Wizard Failures** — Logs display `Connection timeout` or `Access denied from IP: X.X.X.X` errors. This points to IP whitelisting issues in Salesforce's Network Access settings or corporate firewall blocks [$[Salesforce Connector — Troubleshooting Guide]$].

3. **Sync Hangs** — For SAP connectors, logs show repeated `"Cursor validation in progress"` messages followed by silence, indicating OData paging cursor expiry causing indefinite hangs [$[DPLAT-DEF-03]$].

### How to Resolve Sync Errors via Logs

**Step 1: Check the connector health endpoint** — Use `GET /api/v1/connectors/{id}/health` to get the current status [$[Connector Operations Runbook]$].

**Step 2: Review the audit log** — Examine the last 100 events in the connector audit log for error codes and timestamps [$[Connector Operations Runbook]$].

**Step 3: Identify error patterns**:
- **HTTP 5xx errors** = Critical (server-side failures) — triggers PagerDuty alerts within 2 minutes [$[DPLAT-008]$]
- **HTTP 4xx errors** = Warning (client-side issues like expired credentials) [$[DPLAT-008]$]
- **Timeout errors** = Critical (network or connectivity issues) [$[DPLAT-008]$]

**Step 4: Apply targeted fixes**:
- For OAuth errors: Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new tokens [$[Salesforce Connector — Troubleshooting Guide]$]
- For IP issues: Contact your Salesforce admin to add DPLAT IP ranges to **Setup → Security → Network Access** [$[Salesforce Connector — Troubleshooting Guide]$]
- For sync hangs: Note the last successful record ID from logs, then restart the connector service (reduces recovery from ~4 hours to ~15 minutes) [$[DPLAT-DEF-15]$]

### Known Connector Bugs (from Log Analysis)

1. **Recovery takes ~4 hours instead of 30 minutes** — After Salesforce-side outages, automatic recovery takes ~240 minutes despite a 60-minute SLA and 30-minute runbook target. Logs show the connector fails to properly detect service restoration. Workaround: Manual restart reduces recovery to ~15 minutes [$[DPLAT-DEF-15]$].

2. **SAP connector hangs on cursor expiry** — When OData paging cursors expire during large syncs (>10,000 records), the connector enters a blocked state with no graceful failure. Logs show `"Cursor validation in progress"` followed by silence. Requires manual process kill and checkpoint adjustment [$[DPLAT-DEF-03]$].

3. **Alert deduplication merges unrelated incidents** — When multiple connectors trigger alerts within a short window, the deduplication logic incorrectly merges them into a single incident, making it impossible to trace which connector actually failed from the logs alone [$[DPLAT-DEF-14]$].

**Key takeaway**: Always start with the connector audit log and health endpoint. Look for specific error codes (401, 429, 503) and patterns (repeated cursor messages, timeout errors). For persistent issues, gather connector version, tenant ID, last successful sync timestamp, and relevant audit log entries before escalating to support [$[Salesforce Connector — Troubleshooting Guide]$].

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Root Cause Analysis

Connector failures typically stem from one of several root causes, each with distinct symptoms and resolution paths. Below is a structured analysis based on the most common failure scenarios.

### 1. Network and IP Allowlist Issues
**Root Cause:** The most frequent cause of connector failure is the DPLAT connector's outbound IP addresses not being whitelisted in your Salesforce organization's **Network Access** settings. This is documented in [$[DPLAT-DEF-02]$] and the [$[Salesforce Connector — Troubleshooting Guide]$].

**Symptoms:**
- Connection test fails with `Connection timeout` or `Access denied from IP: X.X.X.X` during setup
- Sync jobs fail with generic "connection timeout" errors after initial setup appears successful

**Resolution:**
- Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
- Verify OAuth credentials are valid and not expired
- Confirm your tenant's outbound firewall allows connections to DPLAT endpoints
- If IP whitelisting is not immediately possible, use **OAuth Proxy Mode** which routes connections through your organization's outbound proxy

### 2. OAuth Token Expiration or Revocation
**Root Cause:** The connector's background token refresh mechanism fails when refresh tokens expire, are revoked, or client credentials mismatch. Per the [$[Salesforce Connector — Troubleshooting Guide]$], error codes include `invalid_grant` (refresh token expired/revoked), `invalid_client` (credentials mismatch), and `rate_limit_exceeded` (too many refresh attempts).

**Symptoms:**
- Intermittent `401 Unauthorized` errors in connector logs
- Data sync stops until manually restarted

**Resolution:**
- Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens
- Verify the Salesforce Connected App still exists and is active
- Check audit log for token revocation events
- Enable **Token Refresh Alerting** in connector settings for proactive notification

### 3. API Rate Limits and Object Sync Delays
**Root Cause:** Salesforce governor limits throttle bulk operations, especially when syncing large objects (>100K records) or using complex custom SOQL queries with nested relationships. Retention policies and PII redaction rules can also add processing overhead.

**Symptoms:**
- Stale data in target system; **Last Sync** timestamp is hours behind expected frequency
- No errors logged, but data is not current

**Resolution:**
- Enable incremental sync for large objects
- Simplify custom queries by reducing nested relationship depth
- Adjust sync frequency to comply with your organization's API limit tier
- Use **Staged Sync** mode to prioritize critical objects on a separate schedule

### 4. Known Connector Bugs and Defects
Several documented bugs can cause connector failures:

- **[$[DPLAT-DEF-15]$] — Extended Recovery Time:** After a Salesforce-side outage, connector recovery takes approximately **4 hours** instead of the 30-minute runbook target or 60-minute SLA. A manual restart of the connector service reduces recovery time to ~15 minutes.

- **[$[DPLAT-DEF-03]$] — SAP Connector Sync Hang:** When the SAP connector performs large data syncs (>10,000 records) using OData paging, the process hangs indefinitely after the paging cursor expires. The connector thread enters a blocked state, requiring manual intervention (restarting the connector process and adjusting the sync checkpoint).

- **[$[DPLAT-DEF-01]$] — Health Monitor False Positives:** The Health Monitor incorrectly reports paused connectors as "Unhealthy" with error code `CONNECTION_TIMEOUT`, causing false alerts and unnecessary automatic retry logic.

- **[$[DPLAT-DEF-08]$] — Stale 'Last Sync' Timestamp:** After a manual connector restart, the Health Monitor dashboard continues to display the pre-restart "last sync" timestamp, creating confusion about actual connector health.

- **[$[DPLAT-DEF-14]$] — Alert Deduplication Merges Unrelated Incidents:** When multiple health alerts trigger from different connectors within a short window, the deduplication logic incorrectly merges them into a single incident, making it difficult to trace which connector actually failed.

### 5. Setup Wizard Silent Failures
**Root Cause:** Per [$[DPLAT-DEF-02]$], the Salesforce setup wizard fails silently when connecting to a sandbox org with a restricted IP allowlist. The wizard shows a green checkmark indicating success, but subsequent sync jobs fail with "connection timeout" errors.

**Resolution:** Manually add the platform's outbound IP ranges to the sandbox org's IP allowlist before running the setup wizard.

### How to Resolve Sync Errors

1. **Check connector health endpoint:** `GET /api/v1/connectors/{id}/health`
2. **Review connector audit log** for the last 100 events
3. **Verify data source credentials** have not expired
4. **Check network connectivity** to the data source
5. **If credentials expired**, initiate rotation via workspace admin console
6. **For transient errors**, the retry queue with exponential backoff (max 5 attempts, 30-minute window) handles HTTP 429 and 503 errors automatically per [$[DPLAT-018]$]
7. **For persistent failures**, review the dead-letter queue for records that failed all retry attempts

### Escalation Path

If issues persist after applying resolutions, gather the following before contacting support:
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- Salesforce org ID (first 10 characters)

Include reference to [$[DPLAT-DEF-02]$] when reporting IP allowlist related issues.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)

## Symptom Mapping

`⚠ conflict`

### Primary Question: Why did my connector fail?

Connector failures can be diagnosed by mapping observed symptoms to specific root causes. Based on the troubleshooting documentation, here are the primary failure scenarios:

**1. Setup Wizard Fails**
- **Symptom**: Connection test fails with `Connection timeout` or `Access denied from IP: X.X.X.X` during initial configuration
- **Root Cause**: DPLAT outbound IP addresses not whitelisted in Salesforce **Network Access** settings (per [$[Salesforce Connector — Troubleshooting Guide]$]). Also possible: corporate firewall blocking outbound connections, or expired OAuth credentials.

**2. OAuth Token Refresh Errors**
- **Symptom**: Intermittent `401 Unauthorized` errors with message `OAuth token refresh failed`; data sync stops until manually restarted
- **Root Cause**: Background token refresh mechanism fails. Specific error codes map to:
  - `invalid_grant` → Refresh token expired or revoked
  - `invalid_client` → Client credentials mismatch
  - `rate_limit_exceeded` → Too many refresh attempts

**3. Object Sync Delays**
- **Symptom**: Stale data in target; **Last Sync** timestamp hours behind expected frequency, but no errors logged
- **Root Cause**: API rate limits (Salesforce governor limits), large object volumes (>100K records), complex SOQL queries with nested relationships, or retention policy processing overhead

**4. Health Monitor False Positives**
- **Symptom**: Connector shows **Degraded** status, but manual queries return expected results; compliance officers report false alerts
- **Root Cause**: Health monitor evaluates multiple dimensions that may not reflect actual data availability: latency thresholds (>2s response time triggers warning), partial object failures, or metadata polling failures independent of data sync

**5. Connector Connectivity Failure**
- **Symptom**: Connector status shows "Disconnected" or "Error" in workspace admin console
- **Root Cause**: Expired data source credentials, network connectivity issues to data source, or data source outage (per [$[Connector Operations Runbook]$])

### Related: How do I resolve sync errors?

Resolution steps depend on the specific symptom:

| Symptom | Resolution |
|---------|------------|
| Setup wizard fails | Add DPLAT IP ranges to Salesforce Trusted IP Ranges; verify OAuth credentials; confirm outbound firewall allows DPLAT endpoints; re-run connection test |
| OAuth token refresh errors | Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate**; verify Connected App still exists and is active; check audit log for token revocation events |
| Object sync delays | Enable incremental sync for large objects; simplify custom queries; adjust sync frequency; check PII redaction rules |
| Health Monitor false positives | Review **Health Monitor Details** for specific failing metric; adjust sensitivity thresholds; exclude non-critical objects from monitoring |
| Connectivity failure | Check connector health endpoint (`GET /api/v1/connectors/{id}/health`); review audit log; verify credentials; check network connectivity |

For persistent issues, the connector implements automatic retry with exponential backoff: API 4xx errors retry 2x, API 5xx errors retry 5x over 15 minutes, rate limits (429) throttle and queue, network timeouts retry 3x (per [$[Salesforce Connector — Business Rules]$]). Records that fail all retries are moved to a dead-letter queue for manual review (per [$[DPLAT-018]$]).

### What are known connector bugs?

Based on Jira issue tracking, the following known bugs affect connector reliability:

1. **[$[DPLAT-DEF-15]$] — Connector recovery takes ~4 hours after Salesforce-side outage** (High priority, Open)
   - **Symptom**: After Salesforce API restoration, connector takes ~240 minutes to resume normal operations instead of the 30-minute runbook target or 60-minute SLA
   - **Workaround**: Manual restart of connector service reduces recovery to ~15 minutes
   - **Impact**: SLA violation; data sync blocked during extended recovery window

2. **[$[DPLAT-DEF-08]$] — Health Monitor dashboard shows stale 'last sync' timestamp after manual restart** (Low priority, Open)
   - **Symptom**: After manual connector restart, dashboard continues displaying pre-restart timestamp even though sync is functioning normally
   - **Workaround**: Refresh browser or wait ~5 minutes for automatic dashboard refresh
   - **Impact**: Potential false alarms during incident response; compliance reporting concerns

3. **[$[DPLAT-DEF-03]$] — SAP connector sync hangs indefinitely on OData paging cursor expiry** (High priority, In Progress)
   - **Symptom**: Large sync operations (>10,000 records) hang indefinitely when OData paging cursor expires; connector thread enters blocked state; memory usage grows
   - **Workaround**: Manual intervention required — kill connector process, adjust sync job to start from last checkpoint, or extend OData session timeout
   - **Impact**: Data integrity risk (partial commits, duplicate records, inconsistent state)

### Summary for Symptom Mapping

When diagnosing a connector failure, map the observed symptom to the appropriate category:
- **Connection/authentication issues** → Check IP allowlist, OAuth token validity, and network connectivity
- **Sync performance/staleness** → Investigate API rate limits, object volume, and query complexity
- **Health monitor alerts** → Verify actual data availability before assuming degradation
- **Post-outage behavior** → Be aware of the known 4-hour recovery bug requiring manual restart
- **Large sync operations** → Watch for paging cursor expiry issues, especially with SAP connectors

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Resolution Steps

### Why Did My Connector Fail?

Connector failures typically fall into one of these categories, each with specific resolution steps:

**1. Setup Wizard Failures (IP Allowlist Issues)**
- **Cause**: The DPLAT connector's outbound IP addresses are not whitelisted in your Salesforce organization's Network Access settings, or OAuth credentials are expired/invalid.
- **Resolution** (per [$[Salesforce Connector — Troubleshooting Guide]$]):
  1. Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
  2. Verify OAuth credentials are valid and not expired
  3. Confirm your tenant's outbound firewall allows connections to DPLAT endpoints
  4. Re-run the connection test in the setup wizard
- **Workaround**: Use **OAuth Proxy Mode** if IP whitelisting is not immediately possible.

**2. OAuth Token Refresh Errors**
- **Cause**: The connector's background token refresh mechanism fails, typically due to expired/revoked refresh tokens (`invalid_grant`), client credential mismatches (`invalid_client`), or rate limiting.
- **Resolution** (per [$[Salesforce Connector — Troubleshooting Guide]$]):
  1. Navigate to **Connectors → Salesforce → Settings**
  2. Click **Re-authenticate** to obtain new OAuth tokens
  3. Verify the Salesforce Connected App still exists and is active
  4. Check audit log for token revocation events
- **Workaround**: Enable **Token Refresh Alerting** in connector settings for proactive notification.

**3. Object Sync Delays**
- **Cause**: API rate limits, large object volumes (>100K records), complex SOQL queries, or retention policy overhead.
- **Resolution** (per [$[Salesforce Connector — Troubleshooting Guide]$]):
  1. Enable incremental sync for large objects
  2. Simplify custom queries by reducing nested relationship depth
  3. Adjust sync frequency to comply with your API limit tier
  4. Check if PII redaction rules are adding processing overhead
- **Workaround**: Use **Staged Sync** mode to prioritize critical objects on a separate schedule.

**4. Health Monitor False Positives**
- **Cause**: The health monitor evaluates latency thresholds, partial object failures, or metadata polling issues that don't reflect actual data availability.
- **Resolution** (per [$[Salesforce Connector — Troubleshooting Guide]$]):
  1. Review **Health Monitor Details** to identify the specific failing metric
  2. Adjust sensitivity thresholds in **Connector → Health Settings**
  3. Exclude non-critical objects from health monitoring
  4. Verify network connectivity between DPLAT and Salesforce endpoints
- **Workaround**: Create a custom **Health Check Query** that validates business-critical data freshness directly.

### How Do I Resolve Sync Errors?

For sync errors specifically, the [$[Salesforce — sync error retry queue with dead-letter handling]$] (DPLAT-018) provides an automated resolution mechanism:

- **Automatic retry**: The connector uses exponential backoff (max 5 attempts, 30-minute window) for transient Salesforce API errors (HTTP 429, 503).
- **Dead-letter queue**: Records that fail all retry attempts are moved to a dead-letter queue with full error context (last error code, timestamp, failed payload).
- **Manual reprocessing**: Workspace-admins can view, filter, and manually reprocess dead-letter queue entries via the UI.

If sync errors persist, follow the [$[Connector Operations Runbook]$] connectivity failure playbook:
1. Check connector health endpoint: `GET /api/v1/connectors/{id}/health`
2. Review connector audit log for last 100 events
3. Verify data source credentials have not expired
4. Check network connectivity to data source
5. If credentials expired, initiate rotation via workspace admin console

### What Are Known Connector Bugs?

Several known bugs may cause connector failures:

| Bug | Issue | Workaround |
|-----|-------|------------|
| [$[DPLAT-DEF-15]$] | Connector recovery takes ~4 hours after Salesforce-side outage (violates 30-minute runbook target) | Manual restart of connector service reduces recovery to ~15 minutes |
| [$[DPLAT-DEF-02]$] | Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist | Manually add DPLAT IP ranges to sandbox org's IP allowlist before setup |
| [$[DPLAT-DEF-03]$] | SAP connector sync hangs indefinitely on OData paging cursor expiry | Restart connector and manually adjust sync job to last known checkpoint |
| [$[DPLAT-DEF-08]$] | Health Monitor dashboard shows stale 'last sync' timestamp after manual restart | Refresh browser or wait for next automatic dashboard refresh cycle |
| [$[DPLAT-DEF-13]$] | Health Monitor dashboard takes >10s to load with 50+ connectors | Filter connectors by status or region to reduce displayed count below 30 |
| [$[DPLAT-DEF-14]$] | Alert deduplication merges unrelated incidents from different connectors | Manually split merged incidents in UI or increase deduplication window to 5 minutes |

### Escalation

If issues persist after applying these resolutions, gather the following before contacting support (per [$[Salesforce Connector — Troubleshooting Guide]$]):
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- Salesforce org ID (first 10 characters)

Include reference to DPLAT-DEF-02 when reporting IP allowlist related issues.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Manual Intervention

### Why Did My Connector Fail?

Connector failures requiring manual intervention typically fall into three categories:

**1. Authentication & Token Issues** — According to the [$[Salesforce Connector — Troubleshooting Guide]$], OAuth token refresh errors (HTTP 401) occur when refresh tokens expire or are revoked. The connector's automatic retry mechanism (exponential backoff, max 5 attempts per [$[DPLAT-018]$]) will exhaust its attempts, after which records move to a dead-letter queue requiring manual review. Per [$[DPLAT-003]$], after 3 consecutive refresh failures, an alert is sent, but the workspace-admin must manually re-authenticate via **Connectors → Salesforce → Settings → Re-authenticate**.

**2. Salesforce-Side Outages** — A critical bug documented in [$[DPLAT-DEF-15]$] shows that after a Salesforce API outage, the connector's automatic recovery takes approximately **4 hours** instead of the expected 30-60 minutes. The workaround is a **manual restart of the connector service**, which reduces recovery time to ~15 minutes. This requires on-call intervention and is not suitable for unattended environments.

**3. IP Allowlist Misconfiguration** — Per [$[DPLAT-DEF-02]$], the setup wizard may silently succeed even when a Salesforce sandbox org has a restricted IP allowlist. Subsequent sync jobs fail with generic "connection timeout" errors. The manual fix requires adding DPLAT outbound IP ranges to Salesforce's **Setup → Security → Network Access**.

### How Do I Resolve Sync Errors?

**Manual Intervention Steps:**

1. **Check the Dead-Letter Queue** — Per [$[DPLAT-018]$], records that failed all retry attempts are stored in a dead-letter queue with full error context (last error code, timestamp, failed payload). The workspace-admin UI allows viewing, filtering, and manually reprocessing these entries.

2. **Restart the Connector Service** — For sync hangs (e.g., SAP OData cursor expiry per [$[DPLAT-DEF-03]$]), kill the connector process via `systemctl restart dplat-connector` or the Admin Console. Note the last successfully synced record ID from logs, then update the sync job to start from that checkpoint.

3. **Re-authenticate OAuth Tokens** — Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new tokens. Verify the Salesforce Connected App is still active.

4. **Verify Health Monitor Accuracy** — After manual restart, the Health Monitor dashboard may show a stale "last sync" timestamp (bug [$[DPLAT-DEF-08]$]). Refresh the browser or wait ~5 minutes for the automatic refresh cycle.

### What Are Known Connector Bugs Requiring Manual Intervention?

| Bug | Issue | Manual Workaround |
|-----|-------|-------------------|
| [$[DPLAT-DEF-15]$] | Recovery takes ~4 hours after Salesforce outage | Manual restart reduces to ~15 minutes |
| [$[DPLAT-DEF-03]$] | SAP connector hangs on OData cursor expiry | Kill process, restart from checkpoint |
| [$[DPLAT-DEF-02]$] | Setup wizard silently fails on IP-restricted sandbox | Manually add IP ranges to Salesforce allowlist |
| [$[DPLAT-DEF-08]$] | Health Monitor shows stale timestamp after restart | Refresh browser or wait 5 minutes |
| [$[DPLAT-DEF-14]$] | Alert deduplication merges unrelated incidents | Manually split merged incidents in UI |

**Important Note:** Per the [$[Connector Operations Runbook]$], all connector incidents should be contained and recovery initiated within **30 minutes** of detection. However, the known bug [$[DPLAT-DEF-15]$] means that without manual intervention, recovery can take 4 hours — a clear SLA violation that has already triggered customer complaints and regulatory concerns.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)

## Re-authentication

### Primary Question: Why did my connector fail?

Your connector likely failed due to **OAuth token expiration or revocation**. According to the [$[Salesforce Connector — Troubleshooting Guide]$], the primary symptom is intermittent `401 Unauthorized` errors in connector logs with the message `OAuth token refresh failed`, causing data sync to stop until manually restarted.

The root causes include:

- **`invalid_grant` error** — The refresh token has expired or been revoked by Salesforce
- **`invalid_client` error** — Client credentials (from the Salesforce Connected App) no longer match
- **`rate_limit_exceeded` error** — Too many token refresh attempts were made in a short period

Additionally, per [$[DPLAT-DEF-02]$], a silent failure can occur during initial setup if the Salesforce sandbox org has a restricted IP allowlist — the wizard may appear successful, but subsequent syncs fail with "connection timeout" errors because the platform's outbound IPs aren't whitelisted.

### How do I resolve sync errors?

**Immediate resolution steps** (from the Troubleshooting Guide):

1. Navigate to **Connectors → Salesforce → Settings**
2. Click **Re-authenticate** to obtain new OAuth tokens
3. Verify the Salesforce Connected App still exists and is active in your Salesforce org
4. Check the Salesforce audit log for any token revocation events

**Preventive measures:**

- Enable **Token Refresh Alerting** in connector settings — this notifies workspace admins via email when refresh failures occur, allowing proactive intervention before data sync is impacted (per [$[Salesforce Connector — Troubleshooting Guide]$])
- For IP allowlist issues, contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access** (per [$[DPLAT-DEF-02]$])

**If re-authentication fails**, check whether the Salesforce Connected App has been deleted or its client credentials have changed. You may need to recreate the OAuth integration from scratch.

### What are known connector bugs related to re-authentication?

Based on the available sources, there are no specific bugs documented for the re-authentication flow itself. However, two related issues are known:

1. **[$[DPLAT-DEF-15]$]** — After a Salesforce-side outage, the connector's automatic recovery takes approximately **4 hours** instead of the expected 30-60 minutes. The workaround is a manual restart of the connector service, which reduces recovery time to ~15 minutes. This affects re-authentication because the token refresh mechanism may be stuck during the extended recovery window.

2. **[$[DPLAT-DEF-08]$]** — After a manual connector restart, the Health Monitor dashboard displays a stale "last sync" timestamp (from before the restart) even though the connector is functioning normally. This can create confusion about whether re-authentication was successful. The workaround is to refresh the browser or wait for the next automatic dashboard refresh cycle (~5 minutes).

### Summary

For re-authentication failures, the most common cause is expired or revoked OAuth tokens. The fix is straightforward: use the **Re-authenticate** button in connector settings. If that doesn't work, verify the Connected App's existence and check for IP allowlist restrictions. Enable proactive alerting to catch token refresh issues before they impact data sync.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)

## Cache Clearing

`⚠ conflict`

### Why Did My Connector Fail?

Connector failures related to cache clearing typically stem from **stale or corrupted cached data** that prevents the connector from establishing a fresh connection or completing a sync cycle. According to [$[Salesforce Connector — Troubleshooting Guide]$], the most common cache-related failure scenarios include:

1. **Expired OAuth tokens stored in cache** – The connector's background token refresh mechanism may fail if cached tokens are stale, leading to `401 Unauthorized` errors with messages like "OAuth token refresh failed" (per [$[Salesforce Connector — Troubleshooting Guide]$]).

2. **Retention policy conflicts** – As documented in [$[DPLAT-DEF-04]$], the platform currently applies a **90-day default retention period** for cached connector data, contradicting the documented 30-day policy. This mismatch can cause compliance issues and unexpected behavior when cached data exceeds expected retention windows.

3. **Stale paging cursors** – For SAP connectors, cached OData paging cursors can expire during long-running syncs, causing the connector to hang indefinitely (per [$[DPLAT-DEF-03]$]).

### How Do I Resolve Sync Errors via Cache Clearing?

To resolve sync errors caused by cache issues, follow these steps:

1. **Clear the OAuth token cache** – Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain fresh OAuth tokens. This clears any stale cached credentials (per [$[Salesforce Connector — Troubleshooting Guide]$]).

2. **Manually adjust retention settings** – Since the default cache retention is incorrectly set to 90 days (per [$[DPLAT-DEF-04]$]), manually configure the retention period to **30 days** in each connector's settings to align with documented policies and prevent stale data accumulation.

3. **Restart the connector service** – As noted in [$[DPLAT-DEF-15]$], a manual restart of the connector service after a Salesforce-side outage reduces recovery time from ~4 hours to ~15 minutes, effectively clearing any stuck cache states.

4. **Use the dead-letter queue** – For persistent sync failures, review the dead-letter queue (implemented in [$[DPLAT-018]$]) to identify and manually reprocess records that failed all retry attempts. This queue stores full error context including last error code and timestamp.

### What Are Known Connector Bugs Related to Cache?

| Bug | Description | Workaround |
|-----|-------------|------------|
| [$[DPLAT-DEF-04]$] | Default cache retention is 90 days instead of documented 30 days | Manually set retention to 30 days per connector |
| [$[DPLAT-DEF-15]$] | Recovery after Salesforce outage takes ~4 hours instead of 30-60 minutes | Manual connector restart reduces to ~15 minutes |
| [$[DPLAT-DEF-03]$] | SAP connector hangs on expired OData paging cursors | Restart connector and adjust sync start point |

**Key takeaway**: Cache-related failures are often resolved by clearing stale tokens, adjusting retention settings, or restarting the connector service. The [$[Connector Operations Runbook]$] specifies a **30-minute recovery target** for all connector incidents, but current bugs (per [$[DPLAT-DEF-15]$]) mean actual recovery can take significantly longer without manual intervention.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Sync Reset

### Why Did My Connector Fail?

Connector failures requiring a sync reset typically fall into three categories:

**1. Transient API Errors (HTTP 429, 503)**
The Salesforce connector has a built-in retry mechanism with exponential backoff (max 5 attempts within a 30-minute window) for transient errors, as implemented in [$[DPLAT-018]$]. If all retry attempts fail, records are moved to a dead-letter queue for manual review.

**2. Salesforce-Side Outages**
After a Salesforce outage, the connector recovery process currently takes approximately **4 hours** to fully resume normal operations, according to [$[DPLAT-DEF-15]$]. This violates both the 60-minute SLA (requirement [$[DPLAT-030]$]) and the 30-minute operational runbook target ([$[DPLAT-REQ-15]$]). A manual restart of the connector service reduces recovery time to ~15 minutes.

**3. OAuth Token Expiration**
Connector logs may show intermittent `401 Unauthorized` errors with "OAuth token refresh failed" messages. This can be caused by expired or revoked refresh tokens (`invalid_grant`), client credential mismatches (`invalid_client`), or rate limit exceeded errors, per the [$[Salesforce Connector — Troubleshooting Guide]$].

### How Do I Resolve Sync Errors?

**Step 1: Check Connector Status**
- Verify the connector status in the workspace admin console
- Review the connector audit log for the last 100 events
- Check the Health Monitor dashboard for any alerts

**Step 2: Perform a Sync Reset**
- **For transient errors**: The retry queue should handle these automatically. If not, navigate to the dead-letter queue UI to view and manually reprocess failed records.
- **For OAuth issues**: Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens. Verify the Salesforce Connected App still exists and is active.
- **For post-outage recovery**: If the automatic recovery is taking too long (beyond 30-60 minutes), perform a manual restart of the connector service via `systemctl restart dplat-connector` or the Admin Console. This reduces recovery time to ~15 minutes.

**Step 3: Verify Data Consistency**
After reset, ensure data synchronization achieves 99.9% consistency within 15 minutes of connector restart, as required by [$[DPLAT-REQ-15]$].

### What Are Known Connector Bugs?

| Bug | Impact | Workaround |
|-----|--------|------------|
| **Slow recovery after Salesforce outage** ([$[DPLAT-DEF-15]$]) | Recovery takes ~4 hours instead of 30-60 minutes | Manual restart of connector service |
| **Attachments >5MB silently dropped** ([$[DPLAT-DEF-09]$]) | Large attachments missing from sync, no error logged | Manually compress attachments or use Salesforce API directly |
| **Health Monitor false positives on paused connectors** ([$[DPLAT-DEF-01]$]) | Paused connectors reported as "Unhealthy" with `CONNECTION_TIMEOUT` | Set `health_monitor.enabled=false` for paused connectors |
| **Stale "last sync" timestamp after restart** ([$[DPLAT-DEF-08]$]) | Dashboard shows pre-restart timestamp | Refresh browser or wait for next automatic refresh cycle (~5 min) |

### Key Recommendations for Sync Reset

1. **Enable Token Refresh Alerting** in connector settings to receive proactive notifications before data sync is impacted
2. **Use Staged Sync mode** for critical objects (Accounts, Opportunities) on a separate schedule from archival data to prioritize business-critical data
3. **Configure the retry queue** with appropriate exponential backoff settings (default: max 5 attempts, 30-minute window)
4. **Monitor the dead-letter queue** regularly for permanently failed records that require manual intervention

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)

## Known Issues

Based on the available documentation, here are the primary known issues that can cause connector failures, along with their symptoms, root causes, and resolution guidance.

### 1. Setup Wizard Fails Silently on Restricted IP Allowlists

**Symptom:** The Salesforce connector setup wizard appears to complete successfully (green checkmark), but subsequent data sync jobs fail with generic "connection timeout" errors. This is documented in [$[DPLAT-DEF-02]$].

**Root Cause:** When connecting to a Salesforce sandbox org with a restricted IP allowlist, the wizard does not validate or warn users about this prerequisite. The IP allowlist requirement is documented in the business-rules Confluence page, but the wizard fails silently during the connection test phase.

**Resolution:** Manually add the platform's outbound IP ranges (documented in [$[Salesforce Connector — Troubleshooting Guide]$]) to the Salesforce org's **Network Access** settings under **Setup → Security → Network Access**. Alternatively, use the **OAuth Proxy Mode** if IP whitelisting is not immediately possible.

### 2. OAuth Token Refresh Errors

**Symptom:** Connector logs show intermittent `401 Unauthorized` errors with message "OAuth token refresh failed." Data sync stops until manually restarted.

**Root Cause:** The connector's background token refresh mechanism fails due to expired or revoked refresh tokens (`invalid_grant`), client credentials mismatch (`invalid_client`), or rate limiting on refresh attempts (`rate_limit_exceeded`).

**Resolution:** Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens. Verify the Salesforce Connected App still exists and is active. Enable **Token Refresh Alerting** in connector settings for proactive notification.

### 3. Connector Recovery Takes ~4 Hours After Salesforce-Side Outage

**Symptom:** After a Salesforce-side outage, the connector recovery process takes approximately **4 hours (240 minutes)** to fully resume normal operations, despite a documented 60-minute SLA and 30-minute operational runbook target. This is documented in [$[DPLAT-DEF-15]$].

**Root Cause:** The automatic recovery mechanism fails to meet its targets. During the extended recovery window, data synchronization is completely blocked, causing downstream reporting failures.

**Workaround:** Manual restart of the connector service after Salesforce restoration reduces recovery time to ~15 minutes. However, this requires on-call intervention.

### 4. Health Monitor False Positives on Paused Connectors

**Symptom:** When a connector is intentionally paused, the Health Monitor incorrectly reports it as "Unhealthy" with error code `CONNECTION_TIMEOUT`. This is documented in [$[DPLAT-DEF-01]$].

**Root Cause:** The Health Monitor does not exclude paused connectors from health checks, causing false alerts, incorrect dashboard metrics, and unnecessary automatic retry logic.

**Workaround:** Manually disable health monitoring for paused connectors by setting `health_monitor.enabled=false` configuration flag (requires connector restart).

### 5. Health Monitor Dashboard Shows Stale "Last Sync" Timestamp

**Symptom:** After manually restarting a connector, the Health Monitor dashboard continues to display the "last sync" timestamp from before the restart, even though the connector is functioning normally. This is documented in [$[DPLAT-DEF-08]$].

**Root Cause:** The dashboard does not update the timestamp to reflect the actual time of the most recent synchronization cycle post-restart.

**Workaround:** Refresh the browser or navigate away and back to the Health Monitor page. Alternatively, wait for the next automatic dashboard refresh cycle (approximately 5 minutes).

### 6. Sync Error Retry Queue with Dead-Letter Handling

**Known Issue:** The Salesforce connector previously failed silently on transient API errors. Per [$[DPLAT-018]$], a retry queue with dead-letter handling has been implemented to address this. The retry policy uses exponential backoff (max 5 attempts, 30-minute window) for transient errors (HTTP 429, 503). Records that fail all retry attempts are moved to a dead-letter queue with full error context for manual review.

### Summary of Resolution Steps

For most connector failures, follow this escalation path:
1. **Check credentials** — Re-authenticate OAuth tokens
2. **Verify network access** — Ensure IP allowlists include DPLAT ranges
3. **Review sync configuration** — Enable incremental sync for large objects
4. **Check Health Monitor** — Review specific failing metrics and adjust thresholds
5. **Manual restart** — If recovery takes too long, restart the connector service
6. **Escalate** — If issues persist, gather connector version, tenant ID, last successful sync timestamp, and relevant audit log entries before contacting support

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## DPLAT-DEF-07

The DPLAT-DEF-07 aspect of connector failures focuses on **connector recovery time after upstream outages**, specifically the gap between documented SLAs and actual recovery performance. Here is the answer structured for your subsection:

### Primary Question: Why Did My Connector Fail?

Under DPLAT-DEF-07, connector failures are most commonly caused by **upstream data source outages** (e.g., Salesforce API downtime). When the upstream source becomes unavailable, the connector enters a degraded state and must detect restoration before resuming sync. The critical issue is that **automatic recovery takes approximately 4 hours (240 minutes)** after the upstream source is restored, as documented in [$[DPLAT-DEF-15]$]. This far exceeds both:

- The **60-minute SLA** defined in [$[DPLAT-030]$] (which was marked as "Done" but the recovery logic is not working as specified)
- The **30-minute operational runbook target** defined in [$[DPLAT-REQ-15]$]

Per [$[DPLAT-DEF-15]$], the root cause is a failure in the automatic recovery mechanism — the connector does not properly detect heartbeat signals, rebuild connection pools, or resume queues without manual intervention. The recovery logic uses exponential backoff with a 60-minute cap (per [$[DPLAT-030]$]), but in practice this is not functioning correctly.

### Related: How Do I Resolve Sync Errors?

For DPLAT-DEF-07 specifically, the **workaround** is a **manual restart of the connector service**, which reduces recovery time to approximately **15 minutes** (per [$[DPLAT-DEF-15]$]). Steps:

1. **Identify the outage**: Check the connector health endpoint (`GET /api/v1/connectors/{id}/health`) and review the audit log for the last 100 events, as described in the [$[Connector Operations Runbook]$].
2. **Verify upstream restoration**: Confirm the Salesforce API is operational again.
3. **Manually restart**: Execute `systemctl restart dplat-connector` or use the Admin Console.
4. **Monitor recovery**: After restart, the connector should resume sync within ~15 minutes.

**Important caveat**: The Health Monitor dashboard may show a **stale "last sync" timestamp** after manual restart (documented in [$[DPLAT-DEF-08]$]), which can cause confusion. Refresh the browser or wait ~5 minutes for the dashboard to update.

### What Are Known Connector Bugs?

The primary known bug under DPLAT-DEF-07 is:

- **[$[DPLAT-DEF-15]$] — Connector recovery takes ~4 hours after Salesforce-side outage** (Status: Open, Priority: High). This is a confirmed SLA violation. The automatic recovery mechanism fails to meet the 60-minute SLA and 30-minute runbook target. A manual restart workaround exists but requires on-call intervention, making it unsuitable for unattended environments.

**Regulatory concern** (per compliance comment in [$[DPLAT-DEF-15]$]): This defect causes contractual SLA breaches, and Customer X has already filed a formal complaint regarding data staleness during Salesforce maintenance. Potential revenue is at risk from SLA penalty clauses.

**Summary for DPLAT-DEF-07**: If your connector fails due to an upstream Salesforce outage, expect automatic recovery to take ~4 hours. For faster resolution, perform a manual restart (~15 minutes recovery). The development team is aware of this bug (assigned to dev2@amisol-demo.example) but no fix version has been assigned yet.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-030] Connector recovery SLA — 60-minute target after upstream outage](https://demo-jira.local/browse/DPLAT-030)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-04] Default retention for cached connector data is 90 days, not 30 days as documented](https://demo-jira.local/browse/DPLAT-DEF-04)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)

## Version Conflicts

`⚠ conflict` `⚠ stale`

### Why Did My Connector Fail?

Connector failures due to version conflicts typically manifest as **sync errors** or **connection failures** when the connector's internal state or configuration is incompatible with the data source or platform version. Based on the available sources, the primary version-related issues are:

1. **OAuth Token Version Mismatch**: According to [$[Salesforce Connector — Troubleshooting Guide]$], connectors may fail with `401 Unauthorized` errors when OAuth tokens expire or become invalid. This can occur if the Salesforce Connected App version changes or if token refresh mechanisms are incompatible with the current connector version. The guide lists error codes like `invalid_grant` (refresh token expired/revoked) and `invalid_client` (client credentials mismatch) as common indicators.

2. **Connector Framework Version Incompatibility**: The [$[connector-framework README]$] notes that the framework implements features F-A1, F-A2, and F-A3. If a connector is running an older version (e.g., v2.3) while the platform expects v2.4 features, sync operations may fail. For example, [$[DPLAT-DEF-15]$] documents that after a Salesforce-side outage, recovery takes ~4 hours instead of the expected 30-60 minutes, indicating a version-specific recovery mechanism bug.

3. **API Version Conflicts**: The [$[Connector Operations Runbook]$] describes that sync latency degradation can occur when connector versions don't align with data source API versions. The runbook recommends checking sync metrics against baselines (typically 15 minutes) to detect version-related performance issues.

### How Do I Resolve Sync Errors?

To resolve sync errors caused by version conflicts:

1. **Re-authenticate OAuth Tokens**: Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens, as recommended in the [$[Salesforce Connector — Troubleshooting Guide]$]. This resolves token version mismatches.

2. **Check Connector Version**: Verify the connector version against the platform requirements. The [$[connector-framework README]$] lists related JIRA issues (DPLAT-EPIC-01, DPLAT-EPIC-02, DPLAT-EPIC-03) that define version-specific features. If running an outdated version, upgrade to the latest release.

3. **Enable Retry Queue with Dead-Letter Handling**: [$[DPLAT-018]$] describes a retry queue with exponential backoff (max 5 attempts, 30-minute window) for transient errors (HTTP 429, 503). Records that fail all retries move to a dead-letter queue for manual review. This handles version-related transient failures gracefully.

4. **Manual Restart Workaround**: For severe version conflicts, [$[DPLAT-DEF-15]$] notes that manual restart of the connector service after a Salesforce outage reduces recovery time to ~15 minutes (vs. 4 hours automatic). This is a temporary workaround until the version bug is fixed.

5. **Adjust Sync Configuration**: The [$[Salesforce Connector — Troubleshooting Guide]$] recommends enabling incremental sync for large objects and simplifying custom queries to reduce API consumption, which can mitigate version-related performance issues.

### What Are Known Connector Bugs?

Known bugs related to version conflicts include:

- **[$[DPLAT-DEF-15]$]**: Connector recovery takes ~4 hours after Salesforce-side outage, violating the 60-minute SLA. This is a version-specific bug in the automatic recovery mechanism (observed in v2.3). Workaround: manual restart reduces recovery to ~15 minutes.

- **[$[DPLAT-DEF-03]$]**: SAP connector sync hangs indefinitely on OData paging cursor expiry during large syncs (>10,000 records). The connector enters a blocked state requiring manual intervention. This is related to version-specific OData handling logic.

- **[$[DPLAT-DEF-02]$]**: Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist. The wizard shows success but sync jobs fail with "connection timeout." This is a version-specific validation bug in the setup wizard.

- **[$[DPLAT-DEF-01]$]**: Health Monitor raises false positives on connectors with "Paused" status, treating them as "Unhealthy" with `CONNECTION_TIMEOUT` errors. This causes unnecessary alerts and retry logic.

- **[$[DPLAT-DEF-14]$]**: Health Monitor alert deduplication merges unrelated incidents from different connectors into a single incident, causing confusion during incident review.

- **[$[DPLAT-DEF-13]$]**: Health Monitor dashboard takes >10 seconds to load with 50+ connectors due to sequential API calls.

### Summary

Version conflicts in connectors primarily cause **sync failures**, **OAuth errors**, and **recovery delays**. To resolve them, re-authenticate tokens, upgrade connector versions, enable retry queues, and use manual restart as a workaround. Known bugs include recovery SLA violations, OData paging hangs, silent setup failures, and health monitor false positives. For persistent issues, gather connector version, tenant ID, and audit logs before escalating to support per the [$[Salesforce Connector — Troubleshooting Guide]$] escalation section.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)

## Edge Cases

### Why Did My Connector Fail?

Connector failures can occur due to several edge cases that are not immediately obvious. Here are the most common scenarios:

**1. Silent Setup Failures Due to IP Restrictions**
According to [$[Salesforce Connector — Troubleshooting Guide]$], the setup wizard may appear to complete successfully when connecting to a Salesforce sandbox org with a restricted IP allowlist, but subsequent sync jobs fail with generic "connection timeout" errors. Per [$[DPLAT-DEF-02]$], the wizard does not validate or warn users about this prerequisite, leading to hours of wasted troubleshooting. The fix requires manually adding DPLAT outbound IP ranges to the Salesforce org's **Network Access** settings.

**2. Paused Connectors Triggering False Health Alerts**
Per [$[DPLAT-DEF-01]$], when a connector is intentionally paused by an operator, the Health Monitor incorrectly reports it as "Unhealthy" with error code `CONNECTION_TIMEOUT`. This causes false alerts to on-call teams and unnecessary automatic retry logic. The workaround is to manually disable health monitoring for paused connectors via the `health_monitor.enabled=false` configuration flag.

**3. Extended Recovery After Salesforce-Side Outages**
Per [$[DPLAT-DEF-15]$], after a Salesforce-side outage, the connector recovery process actually takes approximately **4 hours (240 minutes)** to fully resume normal operations, despite the 60-minute SLA defined in requirement DPLAT-030 and the 30-minute target in operational runbooks. During this extended window, data synchronization is completely blocked. The workaround is a manual restart of the connector service, which reduces recovery time to ~15 minutes.

**4. SAP Connector Hangs on OData Paging Cursor Expiry**
Per [$[DPLAT-DEF-03]$], when the SAP connector performs large data synchronizations (>10,000 records) using OData paging, the process hangs indefinitely after the paging cursor expires. The connector thread enters a blocked state, memory usage grows, and the sync never completes or fails gracefully. The workaround requires manual intervention: killing the connector process, noting the last successfully synced record ID, and restarting with a reduced dataset or increased session timeout.

### How Do I Resolve Sync Errors?

**For transient errors (HTTP 429, 503):**
Per [$[DPLAT-018]$], the Salesforce connector automatically retries failed sync operations using a configurable retry queue with exponential backoff (max 5 attempts, 30-minute window). Records that fail all retry attempts are moved to a dead-letter queue with full error context for manual review and reprocessing.

**For OAuth token refresh errors:**
Per [$[Salesforce Connector — Troubleshooting Guide]$], navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens. Verify the Salesforce Connected App still exists and is active. Enable **Token Refresh Alerting** in connector settings for proactive notification.

**For sync delays:**
Enable incremental sync for large objects (>100K records), simplify custom SOQL queries, adjust sync frequency to comply with API limit tiers, and use **Staged Sync** mode to prioritize critical objects on a separate schedule from archival data.

### What Are Known Connector Bugs?

| Bug | Status | Impact | Workaround |
|-----|--------|--------|------------|
| [$[DPLAT-DEF-02]$] Setup wizard fails silently on sandbox with restricted IP allowlist | Open | Silent failure, sync jobs fail with timeout | Manually add DPLAT IP ranges before setup |
| [$[DPLAT-DEF-01]$] Health Monitor false positive on paused connectors | Open | False alerts, unnecessary retry logic | Disable health monitoring for paused connectors |
| [$[DPLAT-DEF-15]$] Recovery takes ~4 hours after Salesforce outage | Open | SLA violation, data staleness | Manual restart reduces to ~15 minutes |
| [$[DPLAT-DEF-03]$] SAP connector hangs on OData cursor expiry | In Progress | Indefinite hang, memory growth | Manual kill and restart with reduced dataset |
| [$[DPLAT-DEF-13]$] Health Monitor dashboard >10s load with 50+ connectors | Open | Browser unresponsiveness, timeouts | Filter connectors or use bulk export |
| [$[DPLAT-DEF-08]$] Stale 'last sync' timestamp after manual restart | Open | Confusing dashboard status | Refresh browser or wait for auto-refresh cycle |

**Key takeaway for edge cases:** The most critical edge cases involve silent failures (IP restrictions, paused connectors) and extended recovery times (4-hour recovery after Salesforce outages, SAP cursor expiry hangs). Always verify IP allowlist configuration before setup, and be prepared for manual intervention when automatic recovery mechanisms fail.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Temporary Fixes

### Why Did My Connector Fail?

Connector failures typically stem from one of several root causes, each with a corresponding temporary workaround:

**1. IP Allowlist / Network Restrictions**  
If your Salesforce connector fails with `Connection timeout` or `Access denied from IP`, the most common cause is that DPLAT's outbound IP ranges are not whitelisted in your Salesforce org's **Network Access** settings.  
**Temporary Fix**: Use **OAuth Proxy Mode**, which routes connections through your organization's outbound proxy. This bypasses the IP whitelisting requirement while your Salesforce admin adds the DPLAT IP range to **Setup → Security → Network Access** (per [$[Salesforce Connector — Troubleshooting Guide]$]).

**2. OAuth Token Expiration**  
Intermittent `401 Unauthorized` errors with `OAuth token refresh failed` indicate expired or revoked refresh tokens.  
**Temporary Fix**: Enable **Token Refresh Alerting** in connector settings. This notifies workspace admins via email when refresh failures occur, allowing proactive intervention before data sync is impacted (per [$[Salesforce Connector — Troubleshooting Guide]$]).

**3. Sync Delays Due to API Rate Limits**  
Objects showing stale data with no error logs often result from Salesforce API rate limits or large object volumes.  
**Temporary Fix**: Use **Staged Sync Mode** — configure critical objects (Accounts, Opportunities) on a separate schedule from archival data. This prioritizes business-critical data and reduces API consumption spikes (per [$[Salesforce Connector — Troubleshooting Guide]$]).

**4. Connector Recovery After Salesforce Outage**  
After a Salesforce-side outage, automatic recovery can take ~4 hours instead of the expected 30-60 minutes (per [$[DPLAT-DEF-15]$]).  
**Temporary Fix**: **Manually restart the connector service** after Salesforce restoration. This reduces recovery time to ~15 minutes (per workaround in [$[DPLAT-DEF-15]$]).

**5. SAP Connector Hangs on OData Paging**  
The SAP connector may hang indefinitely when an OData paging cursor expires during large syncs (>10,000 records).  
**Temporary Fix**: Kill the connector process via `systemctl restart dplat-connector` or the Admin Console, then re-run the sync with a reduced dataset or increased session timeout. Alternatively, configure the SAP proxy to extend OData session timeouts to 60+ minutes (per [$[DPLAT-DEF-03]$]).

### How Do I Resolve Sync Errors?

For transient sync errors (HTTP 429, 503), the connector automatically retries with exponential backoff (max 5 attempts, 30-minute window) via the retry queue (per [$[DPLAT-018]$]). Records that fail all retries move to a dead-letter queue for manual review. **Temporary Fix**: Access the dead-letter queue UI to view, filter, and manually reprocess failed records.

### What Are Known Connector Bugs?

| Bug | Temporary Fix |
|-----|---------------|
| Health Monitor shows stale "last sync" timestamp after manual restart ([$[DPLAT-DEF-08]$]) | Refresh the browser or navigate away and back to the Health Monitor page |
| Alert deduplication merges unrelated incidents ([$[DPLAT-DEF-14]$]) | Manually split merged incidents in the UI, or increase the deduplication window to 5 minutes |
| Health Monitor raises false positives on paused connectors ([$[DPLAT-DEF-01]$]) | Set `health_monitor.enabled=false` configuration flag (requires connector restart) |
| Dashboard takes >10s to load with 50+ connectors ([$[DPLAT-DEF-13]$]) | Filter connectors by status or region to reduce displayed count below 30, or use the bulk export feature |

**Important**: These temporary fixes are intended to restore functionality quickly. For permanent resolutions, refer to the full troubleshooting steps in the [$[Salesforce Connector — Troubleshooting Guide]$] and the [$[Connector Operations Runbook]$].

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)

## Escalation Path

### Why Did My Connector Fail?

Connector failures typically stem from one of several root causes, each with a defined escalation path:

**1. IP Allowlist / Network Issues** — If your Salesforce connector fails with `Connection timeout` or `Access denied`, the most common cause is that DPLAT outbound IP ranges are not whitelisted in your Salesforce organization's Network Access settings. Per the [$[Salesforce Connector — Troubleshooting Guide]$], this is documented in DPLAT-DEF-02. A known bug ([$[DPLAT-DEF-02]$]) causes the setup wizard to silently succeed even when the IP allowlist is restricted, leading to subsequent sync failures.

**2. OAuth Token Expiration** — Intermittent `401 Unauthorized` errors with `OAuth token refresh failed` indicate expired or revoked refresh tokens. The connector's background token refresh mechanism may fail due to `invalid_grant`, `invalid_client`, or `rate_limit_exceeded` errors.

**3. API Rate Limits or Large Data Volumes** — Sync delays without errors often result from Salesforce governor limits throttling bulk operations, or objects exceeding 100K records requiring incremental sync configuration.

**4. Known Bugs** — Several documented defects can cause failures:
- [$[DPLAT-DEF-15]$]: After a Salesforce-side outage, connector recovery takes ~4 hours instead of the 30-minute runbook target or 60-minute SLA. Manual restart reduces this to ~15 minutes.
- [$[DPLAT-DEF-03]$]: SAP connector sync hangs indefinitely on OData paging cursor expiry, requiring manual process restart.
- [$[DPLAT-DEF-01]$]: Health Monitor raises false positives on intentionally paused connectors, causing unnecessary alerts.

### How Do I Resolve Sync Errors?

**Before escalating**, apply these resolutions based on the symptom:

| Symptom | Resolution |
|---------|------------|
| Connection timeout / Access denied | Add DPLAT IP ranges to Salesforce Trusted IP Ranges; verify OAuth credentials; confirm outbound firewall allows DPLAT endpoints |
| OAuth token refresh errors | Re-authenticate via Connectors → Salesforce → Settings; verify Connected App is active |
| Sync delays / stale data | Enable incremental sync for large objects; simplify custom SOQL queries; adjust sync frequency |
| Transient API errors (429, 503) | Automatic retry with exponential backoff (max 5 attempts, 30-minute window) per [$[DPLAT-018]$] |
| Paused connector showing unhealthy | Set `health_monitor.enabled=false` or wait for fix in v2.4 |

**If issues persist**, gather the following before escalating:
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- Salesforce org ID (first 10 characters)
- Reference DPLAT-DEF-02 for IP allowlist issues

### Escalation Matrix

Per the [$[Connector Operations Runbook]$], use this severity-based escalation path:

| Severity | Description | Response SLA | Escalate To |
|----------|-------------|--------------|-------------|
| **P1** | Complete connector outage, multiple tenants affected | 15 minutes | Module lead → VP Engineering |
| **P2** | Single connector degraded, single tenant impact | 30 minutes | Module lead |
| **P3** | Non-critical functionality impaired | 2 hours | Primary on-call |
| **P4** | Minor issue, workaround available | 8 hours | Next business day |

**Escalation contacts:**
- Module lead: connector-lead@mtrnix.example
- VP Engineering: vp-eng@mtrnix.example
- Compliance officer: compliance@mtrnix.example (for PII incidents)

### What Are Known Connector Bugs?

| Bug ID | Description | Status | Workaround |
|--------|-------------|--------|------------|
| [$[DPLAT-DEF-15]$] | Recovery takes ~4 hours after Salesforce outage (violates 30-min runbook target) | Open | Manual restart reduces to ~15 minutes |
| [$[DPLAT-DEF-02]$] | Setup wizard fails silently on sandbox with restricted IP allowlist | Open | Manually add IP ranges before setup |
| [$[DPLAT-DEF-03]$] | SAP connector hangs on OData paging cursor expiry | In Progress | Restart connector; extend session timeout |
| [$[DPLAT-DEF-01]$] | Health Monitor false positive on paused connectors | Open | Disable health monitoring for paused connectors |
| [$[DPLAT-DEF-13]$] | Health Monitor dashboard >10s load with 50+ connectors | Open | Filter connectors or use bulk export |
| [$[DPLAT-DEF-14]$] | Alert deduplication merges unrelated incidents | Open | Manually split incidents; increase dedup window |

### Recovery Procedure

All connector incidents must be contained and recovery initiated within **30 minutes** of detection:
1. **Triage (0-5 min)**: Identify affected tenants, data sources, and severity
2. **Containment (5-10 min)**: Pause affected sync jobs to prevent data corruption
3. **Root cause analysis (10-20 min)**: Review audit logs, metrics, and recent deployments
4. **Recovery action (20-30 min)**: Execute remediation or failover to standby instance

For P1/P2 incidents, the on-call rotation handles initial triage, with escalation to module lead and VP Engineering as needed.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Support Tickets

### Why Did My Connector Fail?

Connector failures typically fall into one of several categories, each with specific root causes and resolution paths:

**Authentication & Connectivity Failures**
- **OAuth token expiration or revocation** — The most common cause, indicated by `401 Unauthorized` errors with messages like `invalid_grant` (token expired/revoked) or `invalid_client` (credentials mismatch). Per the [$[Salesforce Connector — Troubleshooting Guide]$], resolution requires re-authentication via **Connectors → Salesforce → Settings → Re-authenticate**.
- **IP allowlist issues** — If the connection test fails with `Connection timeout` or `Access denied from IP`, your DPLAT outbound IP ranges (203.0.113.0/24 for US-East, 198.51.100.0/24 for EU-West) must be added to Salesforce's **Network Access** settings. Reference DPLAT-DEF-02 when reporting this.
- **Network connectivity** — Corporate firewalls may block outbound connections to DPLAT endpoints. Use **OAuth Proxy Mode** as a workaround if IP whitelisting isn't immediately possible.

**Sync Errors & Retry Behavior**
- **Transient API errors (HTTP 4xx/5xx)** — The connector implements exponential backoff with jitter: 5 attempts with wait times of 0s, 5s, 10s, 20s, and 40s. After five failed attempts, the connector enters `FAILED` state and publishes an alert. Per [$[DPLAT-018]$], records that fail all retries are moved to a **dead-letter queue** with full error context (last error code, timestamp, failed payload). Workspace admins can view, filter, and manually reprocess these entries via the UI.
- **Rate limiting (HTTP 429)** — The connector throttles and queues requests, resuming when the rate limit header allows. Per the [$[Salesforce Connector — Business Rules]$], API 4xx errors are retried 2x with exponential backoff, then quarantined. Quarantined records are retained for 7 days and can be manually reprocessed.
- **Schema mismatches** — The connector skips the mismatched field, logs a `SCHEMA_DRIFT` warning, and continues sync. This is a non-blocking error.

**Known Connector Bugs (Open Tickets)**
- **[DPLAT-DEF-15]** — After a Salesforce-side outage, connector recovery takes approximately **4 hours** instead of the expected 30-60 minutes (SLA violation). Workaround: manual restart of the connector service reduces recovery time to ~15 minutes. This is an **Open** bug with High priority.
- **[DPLAT-DEF-08]** — After manual restart, the Health Monitor dashboard shows a stale "last sync" timestamp. Workaround: refresh the browser or wait for the next automatic refresh cycle (~5 minutes). This is an **Open** bug with Low priority.

### How Do I Resolve Sync Errors?

1. **Check the Health Monitor** — Review the dashboard for degraded status. Per [$[DPLAT-008]$], alerts are sent via PagerDuty and email for sync failures (HTTP 5xx = Critical, HTTP 4xx = Warning, timeout = Critical). Alerts are deduplicated within a 15-minute window.
2. **Review the dead-letter queue** — In the Connector UI, examine failed records with full error context. Manually reprocess entries if needed.
3. **Re-authenticate** — If OAuth tokens are expired, navigate to **Connectors → Salesforce → Settings → Re-authenticate**.
4. **Verify IP allowlist** — Confirm DPLAT IP ranges are added to Salesforce Network Access.
5. **Enable Token Refresh Alerting** — In connector settings, this notifies workspace admins via email when refresh failures occur.
6. **For persistent issues** — Gather connector version, tenant ID, last successful sync timestamp, relevant audit log entries (PII redacted), and Salesforce org ID. Escalate via the support portal referencing DPLAT-DEF-02 for IP-related issues.

### What Are Known Connector Bugs?

| Bug ID | Description | Status | Priority | Workaround |
|--------|-------------|--------|----------|------------|
| [$[DPLAT-DEF-15]$] | Connector recovery takes ~4 hours after Salesforce outage (violates 60-min SLA) | **Open** | High | Manual restart of connector service (~15 min recovery) |
| [$[DPLAT-DEF-08]$] | Health Monitor shows stale "last sync" timestamp after manual restart | **Open** | Low | Refresh browser or wait for auto-refresh (~5 min) |
| [$[DPLAT-DEF-03]$] | SAP connector sync hangs indefinitely on OData paging cursor expiry | **In Progress** | High | Manual restart + adjust sync checkpoint; extend OData session timeout |

**Note**: For the Salesforce connector specifically, the primary open bug is [$[DPLAT-DEF-15]$] regarding recovery time after outages. The SAP-related bug [$[DPLAT-DEF-03]$] is listed for awareness as it affects the broader connector framework.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-011] SAP S/4HANA connector — incremental delta sync via OData change tokens](https://demo-jira.local/browse/DPLAT-011)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Vendor Contact

### Primary Question: Why Did My Connector Fail?

When a connector fails, the root cause often lies in **network or authentication issues** that require coordination with your Salesforce vendor/administrator. According to the [$[Salesforce Connector — Troubleshooting Guide]$], the most common failure scenarios that involve vendor contact are:

1. **IP Allowlist Restrictions**: The DPLAT connector requires outbound IP addresses to be whitelisted in your Salesforce organization's **Network Access** settings. If your Salesforce org (especially a sandbox) has a restricted IP allowlist, the connection test may appear to succeed but sync jobs will fail with "connection timeout" errors. This is documented in bug [$[DPLAT-DEF-02]$], which notes that the setup wizard does not validate this prerequisite, leading to silent failures.

2. **OAuth Token Expiration**: Intermittent `401 Unauthorized` errors with "OAuth token refresh failed" indicate that refresh tokens have expired or been revoked. This requires re-authentication through your Salesforce admin.

3. **Salesforce-Side Outages**: After a Salesforce service outage, the connector recovery process can take approximately **4 hours** instead of the expected 30-60 minutes, as documented in bug [$[DPLAT-DEF-15]$]. This is a known defect requiring vendor coordination.

### How Do I Resolve Sync Errors?

**For IP allowlist issues**: Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access** in Salesforce. Reference DPLAT-DEF-02 when reporting. As a workaround, use **OAuth Proxy Mode** to route connections through your organization's outbound proxy.

**For OAuth errors**: Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new tokens. Verify the Salesforce Connected App is still active.

**For sync delays**: Enable incremental sync for large objects (>100K records), simplify custom SOQL queries, and adjust sync frequency to comply with API limits. Use **Staged Sync** mode to prioritize critical objects.

**For persistent failures**: The retry queue (implemented in [$[DPLAT-018]$]) automatically retries failed syncs with exponential backoff (max 5 attempts, 30-minute window). Records that fail all retries move to a dead-letter queue for manual review.

### What Are Known Connector Bugs?

| Bug ID | Issue | Status | Vendor Contact Needed? |
|--------|-------|--------|----------------------|
| [$[DPLAT-DEF-02]$] | Setup wizard fails silently when sandbox org has restricted IP allowlist | **Open** | Yes — Salesforce admin must whitelist IPs |
| [$[DPLAT-DEF-15]$] | Connector recovery takes ~4 hours after Salesforce outage (vs. 30-min SLA) | **Open** | Yes — coordinate with Salesforce support during outages |
| [$[DPLAT-DEF-01]$] | Health Monitor raises false positives on paused connectors | **Open** | No — internal fix needed |
| [$[DPLAT-DEF-08]$] | Dashboard shows stale "last sync" timestamp after manual restart | **Open** | No — UI refresh issue |

### Escalation Path

If issues persist after applying resolutions, gather the following before contacting support (per the [$[Connector Operations Runbook]$]):
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- Salesforce org ID (first 10 characters)

Include reference to **DPLAT-DEF-02** when reporting IP allowlist related issues. For production incidents, escalate to **connector-lead@mtrnix.example** (module lead) or **vp-eng@mtrnix.example** (VP Engineering) for P1/P2 severity.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)

## Internal Escalation

### Why Did My Connector Fail?

Connector failures typically fall into one of several categories, each with specific escalation paths:

**Authentication & Connectivity Failures** — The most common cause is OAuth token expiration or IP allowlist issues. Per the [$[Salesforce Connector — Troubleshooting Guide]$], if you see `401 Unauthorized` errors with "OAuth token refresh failed," your refresh token may have expired or been revoked. For `Connection timeout` or `Access denied` errors, your DPLAT IP ranges likely need to be whitelisted in Salesforce's Network Access settings (reference DPLAT-DEF-02).

**Transient API Errors** — HTTP 429 (rate limit) and 503 (service unavailable) errors are automatically retried with exponential backoff (up to 5 attempts within a 30-minute window), as implemented in [$[DPLAT-018]$]. If retries are exhausted, records move to a dead-letter queue for manual review.

**Known Bugs Requiring Escalation** — Two critical bugs are currently open:
- **[$[DPLAT-DEF-15]$]**: After a Salesforce-side outage, automatic recovery takes ~4 hours instead of the 30-minute target. The workaround is a manual connector restart, which reduces recovery to ~15 minutes.
- **[$[DPLAT-DEF-03]$]**: The SAP connector hangs indefinitely on OData paging cursor expiry during large syncs (>10,000 records). Manual intervention is required to kill the process and restart from the last checkpoint.

### How Do I Resolve Sync Errors?

**Before escalating**, follow these steps from the [$[Salesforce Connector — Troubleshooting Guide]$]:

1. **Verify credentials** — Navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** to obtain new OAuth tokens.
2. **Check network access** — Confirm DPLAT IP ranges are in Salesforce's Trusted IP Ranges and your corporate firewall allows outbound connections.
3. **Review sync configuration** — Enable incremental sync for large objects (>100K records) and simplify custom SOQL queries.
4. **Check the Health Monitor** — Review the specific failing metric; adjust sensitivity thresholds or exclude non-critical objects from monitoring.

**When to escalate internally** — If issues persist after applying these resolutions, gather the following before contacting support (per the Troubleshooting Guide):
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (with PII redacted)
- Salesforce org ID (first 10 characters)

### What Are Known Connector Bugs?

| Bug | Status | Impact | Workaround |
|-----|--------|--------|------------|
| **[$[DPLAT-DEF-15]$]** — Recovery takes ~4 hours after Salesforce outage | Open, High | SLA violation (target: 30 min) | Manual connector restart (~15 min recovery) |
| **[$[DPLAT-DEF-03]$]** — SAP connector hangs on OData cursor expiry | In Progress, High | Blocks large syncs, requires manual kill | Restart connector, adjust checkpoint |
| **[$[DPLAT-DEF-13]$]** — Health Monitor dashboard slow with 50+ connectors | Open, Medium | >10s load time | Filter connectors or use bulk export |
| **[$[DPLAT-DEF-08]$]** — Stale "last sync" timestamp after restart | Open, Low | Dashboard shows incorrect status | Refresh browser or wait for auto-refresh |

### Escalation Matrix

Per the [$[Connector Operations Runbook]$], use this severity-based escalation:

| Severity | Description | Response SLA | Escalate To |
|----------|-------------|--------------|-------------|
| **P1** | Complete outage, multiple tenants | 15 min | Module lead, VP Engineering |
| **P2** | Single connector degraded | 30 min | Module lead |
| **P3** | Non-critical impairment | 2 hours | Primary on-call |
| **P4** | Minor issue, workaround exists | 8 hours | Next business day |

**Escalation contacts**: Module lead at `connector-lead@mtrnix.example`, VP Engineering at `vp-eng@mtrnix.example`, Compliance officer at `compliance@mtrnix.example` (for PII incidents).

**Important note**: The [$[DPLAT-REQ-15]$] operational runbook targets 30-minute recovery, but [$[DPLAT-DEF-15]$] confirms actual recovery takes ~4 hours after Salesforce-side outages. If you encounter this, escalate as a P1 and apply the manual restart workaround immediately.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)

## Incident Reporting

### Primary Question: Why Did My Connector Fail?

Connector failures can occur for several distinct reasons, each with specific symptoms and root causes:

**1. Connectivity Failures** — The most common cause, typically presenting as "Disconnected" or "Error" status in the workspace admin console. According to [$[Salesforce Connector — Troubleshooting Guide]$], this often stems from:
- DPLAT IP ranges not being whitelisted in your Salesforce organization's **Network Access** settings (error: `Connection timeout` or `Access denied from IP`)
- Corporate firewalls blocking outbound connections to DPLAT endpoints
- Expired OAuth credentials or incorrect refresh tokens

**2. OAuth Token Refresh Errors** — Intermittent `401 Unauthorized` errors with messages like `invalid_grant` (refresh token expired/revoked), `invalid_client` (credentials mismatch), or `rate_limit_exceeded` indicate the connector's background token refresh mechanism has failed. Data sync stops until manually restarted.

**3. Sync Latency and Object Delays** — Objects showing stale data with "Last Sync" timestamps hours behind expected frequency, even without logged errors. Root causes include Salesforce API rate limits, large object volumes (>100K records requiring incremental sync), complex custom SOQL queries, and active retention policies adding processing overhead.

**4. Known Bugs** — Several documented defects can cause failures:
- **DPLAT-DEF-15**: After a Salesforce-side outage, connector recovery takes approximately **4 hours** instead of the 60-minute SLA target. Manual restart reduces this to ~15 minutes.
- **DPLAT-DEF-03**: The SAP connector hangs indefinitely on OData paging cursor expiry during large syncs (>10,000 records), requiring manual process restart.
- **DPLAT-DEF-01**: The Health Monitor raises false positives on intentionally paused connectors, incorrectly reporting them as "Unhealthy" with `CONNECTION_TIMEOUT`.

### Related: How Do I Resolve Sync Errors?

**For connectivity failures**, per the [$[Salesforce Connector — Troubleshooting Guide]$]:
1. Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
2. Verify OAuth credentials are valid and not expired
3. Confirm your tenant's outbound firewall allows connections to DPLAT endpoints
4. Re-run the connection test in the setup wizard

**For OAuth token issues**:
1. Navigate to **Connectors → Salesforce → Settings**
2. Click **Re-authenticate** to obtain new OAuth tokens
3. Verify the Salesforce Connected App still exists and is active
4. Enable **Token Refresh Alerting** in connector settings for proactive notification

**For sync delays**:
1. Enable incremental sync for large objects
2. Simplify custom queries by reducing nested relationship depth
3. Adjust sync frequency to comply with API limit tiers
4. Use **Staged Sync** mode to prioritize critical objects separately

**For known bugs**:
- **DPLAT-DEF-15** (slow recovery): Manual restart of the connector service reduces recovery time to ~15 minutes
- **DPLAT-DEF-03** (SAP hang): Kill the connector process via `systemctl restart dplat-connector` or Admin Console, then re-run sync from last known checkpoint
- **DPLAT-DEF-01** (false positives): Set `health_monitor.enabled=false` configuration flag for paused connectors

### What Are Known Connector Bugs?

| Bug ID | Description | Status | Workaround |
|--------|-------------|--------|------------|
| **DPLAT-DEF-15** | Connector recovery takes ~4 hours after Salesforce outage (violates 60-min SLA) | Open | Manual restart reduces to ~15 min |
| **DPLAT-DEF-03** | SAP connector hangs indefinitely on OData paging cursor expiry | In Progress | Kill process, restart from checkpoint |
| **DPLAT-DEF-01** | Health Monitor false positives on paused connectors | Open | Disable health monitoring for paused connectors |
| **DPLAT-DEF-14** | Alert deduplication merges unrelated incidents from different connectors | Open | Manually split merged incidents or increase dedup window to 5 min |
| **DPLAT-DEF-13** | Health Monitor dashboard takes >10s to load with 50+ connectors | Open | Filter by status/region or use bulk export |

### Incident Reporting Procedure

When reporting a connector failure, gather the following information before contacting support (per the [$[Salesforce Connector — Troubleshooting Guide]$]):
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- Salesforce org ID (first 10 characters)
- Reference **DPLAT-DEF-02** when reporting IP allowlist related issues

The [$[Connector Operations Runbook]$] specifies that all connector incidents must be contained and recovery initiated within **30 minutes** of detection, following this triage timeline:
- **0-5 min**: Identify affected tenants, data sources, and severity
- **5-10 min**: Pause affected sync jobs to prevent data corruption
- **10-20 min**: Review audit logs, metrics, and recent deployments
- **20-30 min**: Execute appropriate remediation or failover

For P1 incidents (complete connector outage, multiple tenants affected), escalate to the module lead and VP Engineering within **15 minutes**. For P2 incidents (single connector degraded), escalate to the module lead within **30 minutes**.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-008] Health Monitor — alerting on connector sync failures (PagerDuty + email)](https://demo-jira.local/browse/DPLAT-008)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📋 [[DPLAT-030] Connector recovery SLA — 60-minute target after upstream outage](https://demo-jira.local/browse/DPLAT-030)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-DEF-14] Health Monitor — alert deduplication merges unrelated incidents](https://demo-jira.local/browse/DPLAT-DEF-14)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-DEF-03] SAP connector sync hangs indefinitely on OData paging cursor expiry](https://demo-jira.local/browse/DPLAT-DEF-03)
- 📋 [[DPLAT-DEF-01] Health Monitor raises false positive on connector with paused status](https://demo-jira.local/browse/DPLAT-DEF-01)
- 📋 [[DPLAT-DEF-08] Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connector](https://demo-jira.local/browse/DPLAT-DEF-08)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
