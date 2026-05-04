# 2.1  Configuration management

_Feature: `F-A1 Salesforce Connector` · Audience: workspace-admin, compliance-officer_

> Managing connection parameters for Salesforce and SAP.

## Connection Setup

To configure the Salesforce connector's connection, follow these steps:

### Prerequisites

Before starting the setup, ensure the following prerequisites are met:

1. **IP Allowlist**: The DPLAT outbound IP addresses must be added to your Salesforce organization's **Network Access** settings. The required IP ranges are:
   - `203.0.113.0/24` (DPLAT US-East, Primary)
   - `198.51.100.0/24` (DPLAT EU-West, Failover)
   
   This is documented in DPLAT-DEF-02. Contact your Salesforce admin to add these ranges under **Setup → Security → Network Access**. If IP whitelisting is not immediately possible, you can use **OAuth Proxy Mode**, which routes connections through your organization's outbound proxy (requires coordination with your network team).

2. **Salesforce User Permissions**: The user performing the OAuth setup must have:
   - `Customize Application` permission
   - `Manage Connected Apps` permission
   - Object-level CRUD on target objects (Account, Contact, etc.)

3. **Connected App Configuration**: A DPLAT-managed Connected App must be created in the target Salesforce org:
   - Navigate to **Setup → App Manager → New Connected App**
   - Enable "Enable OAuth Settings"
   - Add callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
   - Set OAuth scopes: `api`, `refresh_token`, and `webhook` (for real-time sync)

### Setup Wizard Process

Per [$[DPLAT-002]$], the initial setup wizard provides a guided experience:

1. **Enter Credentials**: The workspace admin enters Salesforce credentials (Client ID, Client Secret, Refresh Token) through a secure form with input validation.

2. **Connection Validation**: The wizard validates the Salesforce connection by performing an OAuth token exchange and displays success/failure status. If the connection test fails with errors like `Connection timeout` or `Access denied from IP`, follow the troubleshooting steps below.

3. **Object Selection**: The admin can select which Salesforce objects to sync (Account, Opportunity) with a preview of available fields.

4. **Completion**: Upon completion, the connector appears in the Connector Health Monitor with status "Active" and shows the last sync timestamp.

### Authentication Requirements

The Salesforce Connector uses **OAuth 2.0** for authentication, following the Salesforce Connected App flow (referenced in DPLAT-003 and DPLAT-REQ-03). The authentication flow is:

1. Workspace admin initiates connector setup and is redirected to Salesforce login.
2. User grants permissions via Salesforce OAuth consent screen.
3. DPLAT receives authorization code and exchanges it for access token + refresh token.
4. Tokens are stored encrypted in the tenant's secure vault.
5. Access tokens are automatically refreshed before expiration (60-minute TTL).

Required OAuth scopes:
- `api` — Full API access
- `refresh_token` — Long-lived refresh capability
- `webhook` — Platform Events subscription (for real-time sync)

### Troubleshooting Connection Issues

If the setup wizard fails, common causes include:
- DPLAT IP ranges not added to Salesforce Trusted IP Ranges
- Corporate firewall blocking outbound connections to DPLAT endpoints
- Incorrect OAuth credentials or expired refresh tokens

**Resolution steps**:
1. Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
2. Verify OAuth credentials are valid and not expired
3. Confirm your tenant's outbound firewall allows connections to DPLAT endpoints
4. Re-run the connection test in the setup wizard

### Regarding SAP S/4 Connectivity

The question also asks about SAP S/4 connectivity setup. Based on the available context, the SAP S/4HANA connector has its own setup wizard (per [$[DPLAT-004]$]) with 4 steps: Connection Details, Authentication, Schema Selection, and Review & Connect. The authentication step supports both SAP Cloud Identity Services and on-premise certificate-based options. However, the detailed SAP connection parameters are not provided in the context specifically for the "Connection Setup" subsection of the Salesforce connector documentation. The SAP connector supports both SOAP and OData v4 transport protocols (per [$[DPLAT-REQ-13]$]), with SOAP requiring WS-Security 1.1 with X.509 certificate authentication.

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)

## Authentication

To configure authentication for the Salesforce Connector, you must use **OAuth 2.0** following the Salesforce Connected App flow, as documented in [$[Salesforce Connector — Business Rules]$] and referenced in JIRA issues [$[DPLAT-003]$] and [$[DPLAT-REQ-03]$].

### Authentication Flow

1. **Initiate Setup**: The workspace admin starts the connector setup wizard (per [$[DPLAT-002]$]) and is redirected to Salesforce login.
2. **OAuth Consent**: The user grants permissions via the Salesforce OAuth consent screen.
3. **Token Exchange**: DPLAT receives an authorization code and exchanges it for an access token (60-minute TTL) and a refresh token.
4. **Secure Storage**: Tokens are stored encrypted at rest using **AES-256-GCM** with per-tenant encryption keys in the tenant's secure vault (per [$[DPLAT-REQ-03]$]).
5. **Automatic Refresh**: Access tokens are automatically refreshed 5 minutes before expiry using the stored refresh token, with exponential backoff retry logic (initial delay 30s, max 5 retries, cap at 5 minutes) as specified in [$[DPLAT-003]$].

### Required OAuth Scopes

- `api` — Full API access
- `refresh_token` — Long-lived refresh capability
- `webhook` — Platform Events subscription (for real-time sync)

### Prerequisites

Before authentication can succeed, the workspace admin must:

- **IP Allowlist**: Add DPLAT outbound IP ranges (`203.0.113.0/24` for US-East, `198.51.100.0/24` for EU-West) to Salesforce Network Access settings (per [$[Salesforce Connector — Business Rules]$]).
- **Connected App**: Create a DPLAT-managed Connected App in the Salesforce org with callback URL `https://connect.dplat.io/oauth/salesforce/callback` and the OAuth scopes listed above.
- **User Permissions**: The Salesforce user performing OAuth setup must have `Customize Application` and `Manage Connected Apps` permissions, plus object-level CRUD on target objects.

### Token Refresh Error Handling

Per [$[DPLAT-003]$], if refresh attempts fail:
- After 3 consecutive failures, an alert is sent to the workspace admin via the Connector Health Monitor.
- The connector enters a `Degraded` state during retry windows.
- Common error codes include `invalid_grant` (refresh token expired/revoked), `invalid_client` (credentials mismatch), and `rate_limit_exceeded`.

### SAP S/4HANA Connectivity (Related)

For SAP S/4HANA connectivity (Feature F-A2), authentication differs: it uses **OData v4** and **RFC/IDOC** protocols, requiring network-level access to the SAP landscape. Tenant administrators must configure firewall rules and trust relationships before workspace admin authentication can proceed. This is separate from the Salesforce OAuth flow.

### Summary of Authentication Requirements

| Requirement | Salesforce Connector |
|-------------|---------------------|
| Protocol | OAuth 2.0 (Connected App flow) |
| Token Encryption | AES-256-GCM at rest |
| Token Refresh | Automatic, 5 min before expiry |
| Retry Logic | Exponential backoff (30s–300s, max 5 attempts) |
| Alert on Failure | After 3 consecutive failures |
| IP Allowlist Required | Yes (DPLAT ranges) |
| Callback URL | `https://connect.dplat.io/oauth/salesforce/callback` |

**Sources:**
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Endpoint Config

`⚠ stale`

To configure the Salesforce Connector's endpoint, you need to complete the following steps, which are documented across multiple sources:

### 1. Prerequisites (IP Allowlist)

Before configuring the endpoint, your Salesforce admin must add DPLAT's outbound IP addresses to your Salesforce org's **Network Access** settings. Per [CONFLUENCE] [$[Salesforce Connector — Business Rules]$], the required IP ranges are:

```
# DPLAT US-East (Primary)
203.0.113.0/24

# DPLAT EU-West (Failover)
198.51.100.0/24
```

If IP allowlisting is not immediately possible, the [$[Salesforce Connector — Troubleshooting Guide]$] mentions an **OAuth Proxy Mode** workaround that routes connections through your organization's outbound proxy.

### 2. Create a Connected App in Salesforce

A DPLAT-managed Connected App must be created in your target Salesforce org:
1. Navigate to **Setup → App Manager → New Connected App**
2. Enable **"Enable OAuth Settings"**
3. Add the callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
4. Set the required OAuth scopes: `api`, `refresh_token`, and `webhook` (for real-time sync)

The Salesforce user performing this setup must have `Customize Application` and `Manage Connected Apps` permissions, plus object-level CRUD on target objects.

### 3. Authentication Flow

The connector uses **OAuth 2.0** authentication via the Salesforce Connected App flow. The process is:
1. The workspace admin initiates connector setup and is redirected to Salesforce login
2. User grants permissions via the Salesforce OAuth consent screen
3. DPLAT receives the authorization code and exchanges it for an access token + refresh token
4. Tokens are stored encrypted (AES-256-GCM) in the tenant's secure vault
5. Access tokens are automatically refreshed 5 minutes before expiration (60-minute TTL), with exponential backoff retry logic (initial delay 30s, max 5 retries, cap at 5 minutes)

### 4. Endpoint Configuration via API

For programmatic setup, use the Connector Configuration API. The endpoint configuration is specified in the `data_source` object of the request body:

```json
{
  "name": "Salesforce Production",
  "type": "salesforce",
  "data_source": {
    "instance_url": "https://myorg.salesforce.com",
    "api_version": "v58.0"
  },
  "sync_schedule": "0 */30 * * *",
  "retention_days": 90,
  "pii_handling": {
    "masking_enabled": true,
    "excluded_fields": ["SSN", "credit_card"]
  }
}
```

The API endpoint is `POST /api/v1/connectors` and requires OAuth 2.0 Bearer Token authentication with the `workspace-admin` role and `connectors:write` scope.

### 5. SAP S/4HANA Connectivity (Related)

Per [$[Connector Framework — Module Overview]$], the SAP S/4HANA Connector (feature F-A2) uses **OData v4** for standard CDS views and **RFC/IDOC** for legacy transactional data. It requires network-level access to the SAP landscape, with tenant administrators configuring firewall rules and trust relationships before the workspace admin can authenticate. This is a separate connector from Salesforce and has its own endpoint configuration requirements.

### Authentication Requirements Summary

| Requirement | Salesforce Connector | SAP S/4HANA Connector |
|-------------|---------------------|----------------------|
| **Auth Method** | OAuth 2.0 (Connected App) | OData v4 / RFC |
| **Token Management** | Auto-refresh with exponential backoff | Network-level trust |
| **Required Scopes** | `api`, `refresh_token`, `webhook` | N/A (network-based) |
| **IP Allowlist** | Required (DPLAT ranges) | Required (firewall rules) |
| **Credential Storage** | AES-256-GCM encrypted vault | Tenant-managed |

For the **Endpoint Config** specifically, the key settings are the Salesforce instance URL and API version, which you provide during the initial setup wizard or via the Connector Configuration API.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-017] Salesforce — bulk migration tool from legacy v1 connector](https://demo-jira.local/browse/DPLAT-017)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)

## Mapping

The **Mapping** configuration for the Salesforce Connector focuses on defining how Salesforce objects and their fields correspond to the platform's data model. This is a workspace-level setting managed through the Connector UI or the Connector Configuration API.

### Object Selection and Field Mapping

During initial setup via the guided wizard ([$[DPLAT-002]$]), workspace admins select which Salesforce objects to sync (e.g., Account, Opportunity, Contact, Lead, Case) and preview available fields. The connector supports both standard and custom objects, but custom objects require **explicit schema registration** via the Connector Configuration API before field mappings can be defined ([$[Salesforce Connector — Business Rules]$]).

For custom objects, the field-mapping UI ([$[DPLAT-016]$]) provides a two-column interface where admins can:
- View all detected custom objects with their API names
- Create, edit, and delete field mappings between Salesforce fields and platform data model fields
- Search through available fields
- Validate that each platform data model field maps to at most one Salesforce field per custom object (duplicate mappings trigger clear error messages)

After saving mappings, the next connector sync operation applies the custom mappings and logs the transformation in the audit log with a summary of mapped records.

### Selective Field Mapping for PII Compliance

The connector supports **selective field mapping** to reduce PII exposure at the source ([$[Connector Framework — Module Overview]$]). Workspace admins can configure which fields to include or exclude during mapping. The `pii_handling` configuration in the Connector Configuration API allows setting `masking_enabled: true` and specifying excluded fields (e.g., SSN, credit_card) ([$[Connector Configuration API — Reference]$]).

### SAP S/4HANA Connectivity — Mapping Context

While the primary question focuses on Salesforce, the SAP S/4HANA Connector (F-A2) follows a similar mapping pattern but uses **pre-built mappings** for Finance, Sales, and Materials Management modules ([$[Connector Framework — Module Overview]$]). SAP connectivity requires network-level access to the SAP landscape, with tenant administrators configuring firewall rules and trust relationships before workspace admins can authenticate and define mappings.

### Authentication Requirements

The Salesforce Connector uses **OAuth 2.0** authentication via the Salesforce Connected App flow ([$[Salesforce Connector — Business Rules]$]):
1. Workspace admin initiates setup and is redirected to Salesforce login
2. User grants permissions via OAuth consent screen
3. DPLAT receives authorization code and exchanges it for access + refresh tokens
4. Tokens are stored encrypted (AES-256-GCM) in the tenant's secure vault
5. Access tokens auto-refresh 5 minutes before expiry (60-minute TTL)

Required OAuth scopes: `api` (full API access), `refresh_token` (long-lived refresh), and `webhook` (for real-time sync). The Salesforce user must have `Customize Application` and `Manage Connected Apps` permissions, and DPLAT outbound IP addresses must be allowlisted in the target Salesforce org ([$[Salesforce Connector — Business Rules]$]).

### Summary

The mapping configuration is a two-step process: (1) select objects and define field-level mappings through the UI or API, with validation ensuring no duplicate platform field mappings, and (2) configure PII handling rules. For custom objects, schema registration is required first. All mappings are applied during the next sync cycle and logged for audit purposes.

**Sources:**
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-025] SAP — field type mapping for German locale (DECIMAL/NUMC/CHAR)](https://demo-jira.local/browse/DPLAT-025)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)

## Validation

To validate the Salesforce connector configuration, you must complete the following steps as outlined in the [$[Salesforce Connector — Business Rules]$] and [$[Salesforce Connector — Troubleshooting Guide]$]:

### Primary: How to Validate the Salesforce Connector Configuration

1. **IP Allowlist Validation**: Before testing the connection, ensure DPLAT's outbound IP ranges (`203.0.113.0/24` for US-East and `198.51.100.0/24` for EU-West) are added to your Salesforce org's **Network Access** settings. Per [$[Salesforce Connector — Troubleshooting Guide]$], the most common cause of setup wizard failure is missing IP allowlist entries, resulting in `Connection timeout` or `Access denied from IP: X.X.X.X` errors.

2. **OAuth 2.0 Authentication Validation**: The connector uses the Salesforce Connected App flow. To validate:
   - Confirm the Connected App exists in Salesforce with callback URL `https://connect.dplat.io/oauth/salesforce/callback`
   - Verify OAuth scopes (`api`, `refresh_token`, `webhook`) are enabled
   - Run the connection test in the setup wizard, which performs an OAuth token exchange and displays success/failure status (per [$[DPLAT-002]$])

3. **Connection Test**: The setup wizard validates the connection by performing an OAuth token exchange. If successful, the connector appears in the Connector Health Monitor with status "Active" and shows the last sync timestamp.

### Related: How to Validate SAP S/4 Connectivity

For SAP S/4HANA, validation follows a different pattern:

1. **Transport Protocol Validation**: The connector supports both SOAP (with WS-Security 1.1 and X.509 certificate authentication) and OData v4 transport. Connection health checks execute every 5 minutes with a ≤30 second timeout per protocol (per [$[DPLAT-REQ-13]$]).

2. **Setup Wizard Validation**: The SAP S/4HANA setup wizard includes 4 steps (Connection Details, Authentication, Schema Selection, Review & Connect) with inline validation at each step. Upon completion, a test connection must succeed, and the connector appears with status "Configured" (per [$[DPLAT-004]$]).

3. **Performance Validation**: For full sync, the connector must sustain 5,000 records per minute for 60 minutes without degradation, with end-to-end latency under 200ms per record (p95) (per [$[DPLAT-REQ-04]$]).

### Authentication Requirements for Validation

**Salesforce Connector**:
- OAuth 2.0 with authorization code flow
- Required scopes: `api`, `refresh_token`, `webhook`
- Tokens stored encrypted in tenant vault with 60-minute TTL and automatic refresh
- Salesforce user must have `Customize Application` and `Manage Connected Apps` permissions

**SAP S/4HANA Connector**:
- Supports both SAP Cloud Identity Services and on-premise certificate-based authentication
- SOAP transport requires X.509 certificate authentication
- Automatic retry logic (3 attempts, exponential backoff) for transient failures

### Common Validation Failures and Resolutions

| Issue | Symptom | Resolution |
|-------|---------|------------|
| IP not allowlisted | `Connection timeout` or `Access denied` | Add DPLAT IP ranges to Salesforce Network Access |
| OAuth token refresh failure | `401 Unauthorized` with `OAuth token refresh failed` | Click **Re-authenticate** in connector settings |
| Schema mismatch | Fields skipped with `SCHEMA_DRIFT` warning | Register custom objects via Connector Configuration API |
| Rate limiting | `429` errors | Adjust sync frequency or enable incremental sync |

If validation fails, gather the connector version, tenant ID, last successful sync timestamp, and relevant audit log entries before contacting support (per [$[Salesforce Connector — Troubleshooting Guide]$]).

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)

## Security & Permissions

To configure the Salesforce Connector with a focus on security and permissions, you must complete the following steps:

### Authentication Setup (OAuth 2.0)

The Salesforce Connector uses **OAuth 2.0** following the Salesforce Connected App flow, as documented in [$[Salesforce Connector — Business Rules]$]. The authentication process requires:

1. **Create a DPLAT-managed Connected App** in your Salesforce org:
   - Navigate to Setup → App Manager → New Connected App
   - Enable "Enable OAuth Settings"
   - Add callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
   - Set required OAuth scopes: `api` (full API access), `refresh_token` (long-lived refresh capability), and `webhook` (Platform Events subscription for real-time sync)

2. **Initiate the OAuth flow**: The workspace admin is redirected to Salesforce login, grants permissions via the OAuth consent screen, and DPLAT receives an authorization code which is exchanged for an access token and refresh token. Tokens are stored encrypted in the tenant's secure vault, with automatic refresh before the 60-minute TTL expires.

### Required Permissions

The Salesforce user performing OAuth setup must have:
- `Customize Application` permission
- `Manage Connected Apps` permission
- Object-level CRUD on target objects (Account, Contact, Lead, Opportunity, Case)

### IP Allowlist Requirement

As referenced in DPLAT-DEF-02, Salesforce requires DPLAT outbound IP addresses to be allowlisted in the target org. Add the following IP ranges to Salesforce Network Access settings:
- **DPLAT US-East (Primary):** `203.0.113.0/24`
- **DPLAT EU-West (Failover):** `198.51.100.0/24`

If IP whitelisting is not immediately possible, use **OAuth Proxy Mode** which routes connections through your organization's outbound proxy.

### API Authentication for Programmatic Configuration

For programmatic connector setup via the [$[Connector Configuration API — Reference]$], use:
- **Authentication:** OAuth 2.0 Bearer Token
- **Required Role:** `workspace-admin`
- **Scope:** `connectors:write`

### SAP S/4 Connectivity (Related)

For SAP S/4HANA connectivity, the setup wizard supports two authentication options (per [$[DPLAT-004]$]):
- **SAP Cloud Identity Services** (cloud-based)
- **On-premise certificate-based authentication** (certificate upload)

The SAP connector supports both **SOAP** (with WS-Security 1.1 and X.509 certificate authentication) and **OData v4** transport protocols (per [$[DPLAT-REQ-13]$]). Connection health checks execute every 5 minutes with a ≤30 second timeout per protocol.

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)

## Access Control

### Authentication Requirements

The Salesforce Connector uses **OAuth 2.0** authentication via the Salesforce Connected App flow, as documented in [$[Salesforce Connector — Business Rules]$] and referenced in DPLAT-003 and DPLAT-REQ-03. The authentication process involves:

1. **OAuth Flow**: The workspace admin initiates connector setup and is redirected to Salesforce login. After granting permissions via the OAuth consent screen, DPLAT receives an authorization code and exchanges it for an access token (60-minute TTL) and a refresh token. Tokens are stored encrypted at rest using AES-256-GCM in the tenant's secure vault (per [$[Salesforce Connector — Business Rules]$]).

2. **Required OAuth Scopes**: 
   - `api` — Full API access
   - `refresh_token` — Long-lived refresh capability
   - `webhook` — Platform Events subscription (for real-time sync)

3. **Automatic Token Refresh**: The connector performs a silent token refresh 5 minutes before access token expiry. Failed refresh attempts implement exponential backoff (30s initial delay, max 5 retries, cap at 5 minutes). After 3 consecutive failures, an alert is sent to the workspace admin via the Connector Health Monitor (per [$[DPLAT-003]$]).

### IP Allowlist (Access Control)

As specified in [$[Salesforce Connector — Business Rules]$] and DPLAT-DEF-02, Salesforce requires that DPLAT outbound IP addresses be allowlisted in the target Salesforce org. The required IP ranges are:

```
# DPLAT US-East (Primary)
203.0.113.0/24

# DPLAT EU-West (Failover)
198.51.100.0/24
```

Workspace admins must add these ranges to **Setup → Security → Network Access** in Salesforce. If IP whitelisting is not immediately possible, the **OAuth Proxy Mode** can route connections through the organization's outbound proxy (per [$[Salesforce Connector — Troubleshooting Guide]$]).

### Required Permissions

The Salesforce user performing OAuth setup must have:
- `Customize Application` permission
- `Manage Connected Apps` permission
- Object-level CRUD on target objects (Account, Contact, etc.)

### Connected App Configuration

A DPLAT-managed Connected App must be created in the target Salesforce org:
1. Navigate to Setup → App Manager → New Connected App
2. Enable "Enable OAuth Settings"
3. Add callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
4. Set OAuth scopes as listed above

### SAP S/4HANA Connectivity (Related)

For SAP S/4HANA connectivity (Feature F-A2), the connector uses **OData v4** and **RFC/IDOC** protocols. This requires network-level access to the SAP landscape, with tenant administrators configuring firewall rules and trust relationships before workspace admin authentication (per [$[Connector Framework — Module Overview]$]). The SAP connector follows the same access control model with tenant-level network policies and workspace-level credential management.

### Access Control Summary

| Aspect | Requirement |
|--------|-------------|
| Authentication | OAuth 2.0 with Connected App |
| IP Allowlist | DPLAT IP ranges (203.0.113.0/24, 198.51.100.0/24) |
| Token Storage | AES-256-GCM encrypted in tenant vault |
| Token Refresh | Automatic, 5 min before expiry, exponential backoff |
| Admin Role | `workspace-admin` role required |
| API Access | OAuth 2.0 Bearer Token with `connectors:write` scope |

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)

## Scopes

The **Scopes** aspect of configuring the Salesforce Connector refers specifically to the **OAuth 2.0 authorization scopes** required during the authentication setup. These scopes define what permissions the connector has when accessing your Salesforce org.

### Required OAuth Scopes

According to [$[Salesforce Connector — Business Rules]$], the Salesforce Connector requires the following three OAuth scopes during the Connected App configuration:

1. **`api`** — Grants full API access to read and write Salesforce data
2. **`refresh_token`** — Enables long-lived refresh capability so the connector can automatically obtain new access tokens without requiring manual re-authentication
3. **`webhook`** — Required for subscribing to Platform Events, which enables near real-time sync (webhook-driven mode)

These scopes are configured when creating the DPLAT-managed Connected App in your Salesforce org. The setup process involves:
- Navigating to **Setup → App Manager → New Connected App** in Salesforce
- Enabling "Enable OAuth Settings"
- Adding the callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
- Selecting the three scopes listed above

### Authentication Flow and Scope Application

The OAuth 2.0 authentication flow works as follows (per [$[Salesforce Connector — Business Rules]$]):

1. The workspace admin initiates connector setup and is redirected to the Salesforce login page
2. The user grants permissions via the Salesforce OAuth consent screen, which displays the requested scopes
3. DPLAT receives an authorization code and exchanges it for an access token + refresh token
4. Tokens are stored encrypted in the tenant's secure vault
5. Access tokens are automatically refreshed before expiration (60-minute TTL)

### Scope-Related Considerations

- The `webhook` scope is only available on **Enterprise and Unlimited** Salesforce editions. If your org uses a different edition, you must use scheduled batch sync modes instead of near real-time sync.
- For **custom objects**, the same OAuth scopes apply, but additional schema registration is required via the Connector Configuration API before sync can begin (based on [$[Salesforce Connector — Business Rules]$]).
- The scopes are set at the Connected App level and apply to all objects the connector syncs. There is no per-object scope configuration.

### SAP S/4HANA Connectivity Note

Regarding the related question about SAP S/4HANA connectivity: The SAP S/4HANA Connector (Feature F-A2) uses **OData v4** and **RFC/IDOC** protocols, not OAuth scopes. It requires network-level access to the SAP landscape, including firewall rules and trust relationships configured by the tenant administrator before the workspace admin can authenticate (based on [$[Connector Framework — Module Overview]$]). The authentication requirements for SAP S/4HANA are fundamentally different from the Salesforce OAuth scope model.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)

## Encryption

`⚠ stale`

The Salesforce Connector implements encryption at multiple levels to secure sensitive data, particularly OAuth authentication tokens and cached Salesforce records.

### OAuth Token Encryption

According to [$[DPLAT-REQ-03]$], all OAuth access and refresh tokens obtained during Salesforce authentication must be encrypted at rest using **AES-256-GCM** with unique per-tenant encryption keys. This requirement is implemented in the connector's credential storage:

- **Algorithm**: AES-256-GCM (Galois/Counter Mode)
- **Key Management**: Each tenant has a unique encryption key
- **Performance**: Encryption/decryption operations must complete within 50ms to maintain the connector's <200ms response time SLA
- **Compliance**: Supports FIPS 140-2 Level 2 validated cryptographic modules for regulated tenants
- **Key Rotation**: Automated encryption key rotation every 90 days with zero-downtime re-encryption of existing tenant tokens

Per [$[DPLAT-003]$], the connector stores OAuth tokens encrypted in the tenant's secure credential store, and the token refresh mechanism (which runs 5 minutes before access token expiry) uses these encrypted credentials. The retry logic for failed refresh attempts implements exponential backoff (initial delay 30s, max 5 retries, cap at 5 minutes).

### Cached Data Encryption

As documented in [$[Salesforce Connector — Business Rules]$], the Salesforce Connector maintains a local cache of synced records. This cached data is **encrypted at rest using AES-256** and is never exposed outside the tenant boundary. The cached data includes:
- Full record snapshots (all synced fields)
- Change tracking metadata (last modified timestamp, modifying user)
- Relationship pointers (parent-child links)

The default retention period for cached data is 30 days, with optional extension up to 90 days for compliance requirements.

### Authentication Flow with Encryption

The complete authentication flow, as described in the business rules document, ensures encryption at every stage:

1. Workspace admin initiates connector setup and is redirected to Salesforce login
2. User grants permissions via Salesforce OAuth consent screen
3. DPLAT receives authorization code and exchanges it for access token + refresh token
4. **Tokens are stored encrypted in the tenant's secure vault** (AES-256-GCM)
5. Access tokens are automatically refreshed before expiration (60-minute TTL)

### Setup Prerequisites for Encryption

Before configuring the connector, workspace admins must ensure:
- The Salesforce Connected App is properly configured with callback URL `https://connect.dplat.io/oauth/salesforce/callback`
- Required OAuth scopes include `api`, `refresh_token`, and `webhook`
- The Salesforce user performing setup has `Customize Application` and `Manage Connected Apps` permissions

### SAP S/4 Connectivity (Related)

Regarding the related question about SAP S/4 connectivity: The SAP connector uses different transport protocols (SOAP with WS-Security 1.1 and X.509 certificate authentication, or OData v4) as specified in [$[DPLAT-REQ-13]$]. The SAP connector's encryption requirements are not detailed in the provided context, but the connector supports both legacy and modern transport protocols with automatic retry logic for transient failures.

**Sources:**
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)

## Audit

Based on the provided sources, here is how to configure the Salesforce Connector, specifically focusing on the **Audit** aspect.

### Primary Question: How do I configure the Salesforce connector?

The configuration process involves several steps, all of which are recorded in the audit log for compliance and troubleshooting.

1.  **Prerequisites (IP Allowlist & Permissions):** Before starting, a workspace admin must ensure the DPLAT outbound IP ranges are allowlisted in the Salesforce org's **Network Access** settings (per [$[Salesforce Connector — Business Rules]$] and DPLAT-DEF-02). The Salesforce user performing the setup also needs `Customize Application` and `Manage Connected Apps` permissions.

2.  **Initial Setup via Wizard:** The guided setup wizard ([$[DPLAT-002]$]) allows the admin to enter credentials (Client ID, Client Secret, Refresh Token) through a secure form. The wizard validates the connection via an OAuth token exchange and allows the selection of objects to sync (e.g., Account, Opportunity). Upon completion, the connector appears in the Health Monitor as "Active". **All configuration changes made during this process are recorded in the audit log with a timestamp, actor, and diff** (per [$[Connector Configuration API — Reference]$]).

3.  **Authentication (OAuth 2.0):** The connector uses OAuth 2.0 with a Salesforce Connected App flow ([$[Salesforce Connector — Business Rules]$]). Tokens are stored encrypted (AES-256-GCM) in the tenant's secure vault ([$[DPLAT-003]$]). The connector automatically refreshes the access token 5 minutes before expiry. **Failed refresh attempts are logged**, and after 3 consecutive failures, an alert is sent to the admin via the Health Monitor ([$[DPLAT-003]$]).

4.  **Programmatic Configuration (API):** For advanced or automated setups, the Connector Configuration API ([$[Connector Configuration API — Reference]$]) allows admins to create or update connector instances. The API documentation explicitly states: **"All configuration changes are recorded in the audit log with timestamp, actor, and diff"**, ensuring full traceability.

### Related: How do I set up SAP S/4 connectivity?

The provided sources do not contain a step-by-step guide for setting up SAP S/4 connectivity. However, they do specify the **authentication requirements** and **performance constraints** for the SAP connector.

- **Transport Protocols:** The SAP S/4 connector must support both SOAP (with WS-Security 1.1 and X.509 certificate authentication) and OData v4 transport ([$[DPLAT-REQ-13]$]).
- **Performance:** It must sustain a throughput of 5,000 records per minute during a full sync ([$[DPLAT-REQ-04]$]).
- **Large Data Handling:** For large result sets, the connector uses server-side paging with a configurable `page_size` (default 2000, range 500-10000) and writes progress checkpoints to the audit log every 10,000 records for job resumption ([$[DPLAT-012]$]).
- **Known Issues:** There are two open bugs: records updated within 1 second of the last cursor can be skipped during delta sync ([$[DPLAT-DEF-12]$]), and German umlauts in CHAR fields may be returned as null ([$[DPLAT-DEF-11]$]).

### What are the authentication requirements?

- **Salesforce Connector:** Uses **OAuth 2.0** with the following required scopes: `api`, `refresh_token`, and `webhook` (for real-time sync). The setup requires a DPLAT-managed Connected App in the Salesforce org with a specific callback URL ([$[Salesforce Connector — Business Rules]$]).
- **SAP S/4 Connector:** Supports **SOAP with X.509 certificate authentication** (WS-Security 1.1) and **OData v4** transport ([$[DPLAT-REQ-13]$]).

### Audit-Specific Summary

For the **Audit** subsection, the key takeaway is that the Salesforce connector is designed with auditability in mind. Every configuration change, authentication attempt (including failures), and data sync operation is logged. The audit log captures:
- **Configuration changes:** Timestamp, actor, and the diff of what changed ([$[Connector Configuration API — Reference]$]).
- **Authentication events:** OAuth token refresh failures and revocation events ([$[Salesforce Connector — Troubleshooting Guide]$]).
- **Data sync errors:** Specific error types like `ERROR_4XX`, `ERROR_5XX`, `RATE_LIMITED`, and `SCHEMA_DRIFT` are logged with payloads and stack traces ([$[Salesforce Connector — Business Rules]$]).
- **Quarantined records:** Records that fail to sync are quarantined for 7 days and can be exported for audit purposes ([$[Salesforce Connector — Business Rules]$]).

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)

## Operational Limits

### Configuration of the Salesforce Connector

To configure the Salesforce Connector, workspace administrators use a guided setup wizard that follows OAuth 2.0 authentication via the Salesforce Connected App flow. The process involves:

1. **Prerequisites**: The Salesforce user must have `Customize Application` and `Manage Connected Apps` permissions, plus object-level CRUD on target objects. DPLAT outbound IP addresses must be allowlisted in the target Salesforce org (per [$[Salesforce Connector — Business Rules]$]).

2. **Setup Wizard**: As described in [$[DPLAT-002]$], the wizard allows entering Salesforce credentials (Client ID, Client Secret, Refresh Token) through a secure form, validates the connection via OAuth token exchange, and lets the admin select which objects to sync (Account, Opportunity) with field preview.

3. **API Configuration**: The Connector Configuration API (per [$[Connector Configuration API — Reference]$]) supports programmatic creation with parameters like `instance_url`, `api_version`, `sync_schedule`, `retention_days`, and `pii_handling`.

### Operational Limits

The Salesforce Connector operates under several constraints that define its operational boundaries:

**Sync Frequency Limits**:
- Near real-time (webhook-driven): Latency under 5 seconds, available only on Enterprise and Unlimited Salesforce editions
- Scheduled batch (hourly): Full delta sync every hour
- Scheduled batch (daily): Full snapshot sync at midnight UTC
- Default: near real-time for standard objects, hourly batch for custom objects

**API Rate Limits**:
- The connector implements adaptive backoff to respect Salesforce API rate limits (per [$[DPLAT-REQ-12]$])
- Exponential backoff starts at 1 second, doubles per retry, with a 60-second maximum cap
- ±20% random jitter applied to prevent thundering herd
- Maximum 5 retry attempts per failed request
- HTTP 429 status codes and `Retry-After` headers are parsed and respected
- Per-tenant rate limit state is maintained separately to avoid cross-tenant interference

**Error Handling Limits**:
- API 4xx errors: Retry 2x with exponential backoff, then quarantine
- API 5xx errors: Retry 5x over 15 minutes, then alert admin
- Rate limit (429): Throttle and queue; resume when header allows
- Network timeout: Retry 3x; mark record as `SYNC_PENDING`
- Schema mismatch: Skip field; log warning; continue sync
- Quarantined records retained for 7 days

**Data Retention Limits**:
- Default cache retention: 30 days
- Maximum configurable retention: 90 days (subject to additional storage costs)
- Cached data encrypted at rest using AES-256

**Object Scope Limits**:
- Standard objects supported: Account, Contact, Lead, Opportunity, Case (read/write, no delete)
- Custom objects: Read supported, write requires explicit schema registration via Connector Configuration API
- Custom objects require field mappings and transformation rules before enabling sync

### SAP S/4 Connectivity Setup

For SAP S/4HANA connectivity (related feature F-A2), the setup follows a similar wizard pattern with 4 steps: Connection Details, Authentication, Schema Selection, and Review & Connect (per [$[DPLAT-004]$]). Authentication supports both SAP Cloud Identity Services and on-premise certificate-based options. The SAP connector must sustain 5,000 records per minute for full sync (per [$[DPLAT-REQ-04]$]) and supports both SOAP and OData v4 transport protocols (per [$[DPLAT-REQ-13]$]).

### Authentication Requirements

For the Salesforce Connector:
- **Protocol**: OAuth 2.0 via Salesforce Connected App flow
- **Required OAuth scopes**: `api` (full API access), `refresh_token` (long-lived refresh), `webhook` (Platform Events subscription for real-time sync)
- **Token management**: Access tokens have 60-minute TTL, automatically refreshed; tokens stored encrypted in tenant's secure vault
- **IP allowlist**: DPLAT outbound IP ranges must be added to Salesforce Network Access settings (203.0.113.0/24 for US-East, 198.51.100.0/24 for EU-West)

For SAP S/4:
- Supports SOAP with WS-Security 1.1 and X.509 certificate authentication
- Supports OData v4 with batch operations (≥50 requests per batch)
- Connection health checks every 5 minutes with ≤30 second timeout per protocol

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-REQ-12] Salesforce — respect upstream API rate limits with adaptive backoff](https://demo-jira.local/browse/DPLAT-REQ-12)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)

## Throughput

The Salesforce Connector's throughput is primarily governed by its **sync frequency modes** and **API rate limit handling**, rather than a single "throughput" setting. Here's how to configure it for optimal throughput:

### Sync Frequency Configuration

The connector supports three throughput modes, configurable per-object in the **Connector Configuration UI**:

1. **Near real-time (webhook-driven):** Triggers on create/update events via Platform Events. Latency < 5 seconds. Available on Enterprise and Unlimited Salesforce editions. This is the **default for standard objects** (Account, Contact, Lead, Opportunity, Case).

2. **Scheduled batch (hourly):** Full delta sync every hour. Suitable for high-volume orgs. This is the **default for custom objects**.

3. **Scheduled batch (daily):** Full snapshot sync at midnight UTC. Lowest API consumption.

To change the mode per object, navigate to the Connector Configuration UI and override the default setting.

### API Rate Limit Management

Throughput is constrained by Salesforce's API governor limits. The connector handles this automatically:

- **Rate limit (HTTP 429):** The connector throttles and queues requests, resuming when the `X-RateLimit-Reset` header allows (per [CONFLUENCE] Salesforce Connector — Business Rules).
- **API 4xx errors:** Retried 2x with exponential backoff, then quarantined.
- **API 5xx errors:** Retried 5x over 15 minutes, then alerts the admin.

### Programmatic Throughput Configuration via API

Using the **Connector Configuration API** (per [CONFLUENCE] Connector Configuration API — Reference), you can set the sync schedule with a cron expression:

```json
{
  "sync_schedule": "0 */30 * * *",
  "retention_days": 90
}
```

The `sync_schedule` field controls how frequently the connector polls for changes, directly impacting throughput. The API also supports partial updates to adjust the schedule without service interruption.

### Authentication Requirements for Throughput

Authentication uses **OAuth 2.0** with the Salesforce Connected App flow (per [CONFLUENCE] Salesforce Connector — Business Rules). Required OAuth scopes:
- `api` — Full API access
- `refresh_token` — Long-lived refresh capability
- `webhook` — Platform Events subscription (for real-time sync)

The connector automatically refreshes tokens 5 minutes before expiry (per [JIRA] DPLAT-003), ensuring uninterrupted throughput. Failed refresh attempts use exponential backoff (30s initial delay, max 5 retries, cap at 5 minutes).

### SAP S/4 Connectivity (Related)

For SAP S/4 throughput, the requirement is to **sustain 5,000 records per minute** for full sync operations (per [JIRA] DPLAT-REQ-04). The SAP connector uses server-side paging with configurable `page_size` (500–10,000 records per page) and stream processing to handle large result sets without memory exhaustion (per [JIRA] DPLAT-012). Both SOAP and OData v4 transport protocols are supported (per [JIRA] DPLAT-REQ-13).

### Key Takeaway for Throughput

For the Salesforce Connector, throughput is not a single numeric setting but is achieved by:
1. Selecting the appropriate sync frequency mode (real-time vs. batch)
2. Configuring the sync schedule via the API or UI
3. Letting the built-in rate limit handling manage API consumption
4. Ensuring OAuth tokens refresh automatically to avoid interruptions

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)

## Rate Limits

The Salesforce Connector's rate limit configuration is handled through a combination of **adaptive backoff logic** (built into the connector framework) and **API-level rate limiting** (configurable via environment variables). Here is how to configure and understand rate limits specifically for this connector:

### 1. Adaptive Backoff for Upstream Salesforce API Rate Limits

Per [JIRA] [DPLAT-REQ-12], the Salesforce connector automatically implements **adaptive backoff** to respect Salesforce's own API rate limits and prevent HTTP 429 errors. This is configured as follows:

- **Backoff Algorithm**: Exponential backoff starting at **1 second**, doubling per retry, with a maximum cap of **60 seconds**.
- **Jitter**: ±20% random jitter is applied to each backoff interval to prevent thundering herd.
- **Retry Limit**: Maximum **5 retry attempts** per failed request before the operation fails.
- **Rate Limit Detection**: The connector monitors HTTP 429 status codes and the `Retry-After` header, parsing and respecting server-specified wait times.
- **Per-Tenant Tracking**: Separate rate limit state is maintained per tenant/workspace to avoid cross-tenant interference.
- **Logging**: Warning logs are emitted when rate limits are encountered, including tenant ID, endpoint, and backoff duration.

This behavior is **automatic** and does not require manual configuration by the workspace admin — it is built into the connector framework as part of feature F-A3 (configurable retry and circuit breaker patterns).

### 2. Connector Configuration API Rate Limits

The Connector Configuration API (used to programmatically create or update connector instances) has its own rate limits, as documented in [CONFLUENCE] [$[Connector Configuration API — Reference]$]:

| Tier | Requests/Minute | Burst |
|------|-----------------|-------|
| Standard | 60 | 100 |
| Enterprise | 300 | 500 |

Rate limit headers are included in API responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining in window
- `X-RateLimit-Reset`: Unix timestamp for window reset

You can customize the API rate limit using the environment variable `CONNECTOR_API_RATE_LIMIT` (default: `60` requests/min), as shown in the Connector Configuration API reference.

### 3. Environment Variable for Custom Rate Limits

From the [$[Connector Configuration API — Reference]$], the following environment variable controls connector API behavior:

| Variable | Description | Default |
|----------|-------------|---------|
| `CONNECTOR_API_RATE_LIMIT` | Custom rate limit (requests/min) | `60` |

To set a custom rate limit, configure this variable in your deployment environment (e.g., via `docker-compose.yml` or Kubernetes ConfigMap).

### 4. Related: SAP S/4 Connectivity and Authentication Requirements

**SAP S/4 connectivity** is not covered in the provided context. The available documentation focuses exclusively on the Salesforce connector. For SAP S/4 connectivity, you would need to consult separate documentation.

**Authentication requirements** for the Salesforce connector are as follows (per [CONFLUENCE] [$[Salesforce Connector — Business Rules]$]):
- **OAuth 2.0** with the Salesforce Connected App flow.
- Required OAuth scopes: `api`, `refresh_token`, and `webhook` (for real-time sync).
- Tokens are stored encrypted (AES-256-GCM) in the tenant's secure vault.
- Access tokens are automatically refreshed 5 minutes before expiry (per [JIRA] [DPLAT-003]).

### Summary

To configure rate limits for the Salesforce Connector:
1. **No action needed** for upstream Salesforce API rate limits — adaptive backoff is built-in and automatic.
2. **Optionally customize** the Connector Configuration API rate limit via the `CONNECTOR_API_RATE_LIMIT` environment variable (default: 60 req/min).
3. **Monitor** rate limit events via warning logs and the `X-RateLimit-*` headers in API responses.

**Sources:**
- 📋 [[DPLAT-REQ-12] Salesforce — respect upstream API rate limits with adaptive backoff](https://demo-jira.local/browse/DPLAT-REQ-12)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-REQ-02] Connector framework rate-limiting — fairness across tenants](https://demo-jira.local/browse/DPLAT-REQ-02)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-035] PII — API rate limiting per tenant (max 1k req/min)](https://demo-jira.local/browse/DPLAT-035)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-01] Connector data sync latency budget — 99p < 5 minutes per 10k records](https://demo-jira.local/browse/DPLAT-REQ-01)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-DEF-13] Health Monitor — dashboard takes >10s to load with 50+ connectors](https://demo-jira.local/browse/DPLAT-DEF-13)

## Payload Size

Based on the available documentation, the Salesforce Connector configuration process involves several steps, but **there is no specific "Payload Size" configuration option documented** for the Salesforce Connector within the provided sources.

### How to Configure the Salesforce Connector

The general configuration process for the Salesforce Connector involves:

1. **Authentication Setup**: The connector uses **OAuth 2.0** via a Salesforce Connected App flow. Required OAuth scopes include `api`, `refresh_token`, and `webhook` (per [$[Salesforce Connector — Business Rules]$]).

2. **IP Allowlist**: Before setup, workspace admins must ensure DPLAT outbound IP addresses (`203.0.113.0/24` for US-East, `198.51.100.0/24` for EU-West) are added to the Salesforce org's Network Access settings (per [$[Salesforce Connector — Business Rules]$]).

3. **Connected App Configuration**: Create a DPLAT-managed Connected App in Salesforce with callback URL `https://connect.dplat.io/oauth/salesforce/callback` and the required OAuth scopes.

4. **Object Selection**: Through the Connector UI, workspace admins can select which Salesforce objects to sync (Account, Contact, Lead, Opportunity, Case, and custom objects with schema registration).

5. **Sync Schedule**: Configure sync frequency as near real-time (webhook-driven), hourly batch, or daily batch.

### Payload Size Considerations

While there is no explicit "Payload Size" configuration setting, the following payload-related information is relevant:

- **Attachment Size Limitation**: According to [$[DPLAT-DEF-09]$], there is a known bug where the Salesforce connector **silently drops attachments larger than 5MB** during sync. This is documented as a defect (status: Open) with no error logged when attachments exceed this threshold. The expected behavior is that attachments up to Salesforce's 25MB limit should be synced.

- **API Configuration**: The [$[Connector Configuration API — Reference]$] shows that the `CONNECTOR_CONFIG_MAX_SIZE` environment variable controls the maximum request body size for the Connector Configuration API itself (default: 1,048,576 bytes / 1MB), but this applies to API requests, not to Salesforce data payloads.

- **Sync Mode Impact**: The connector supports Bulk API v2 for historical backfills (per [$[Connector Framework — Module Overview]$]), which may handle larger payloads differently than streaming API.

### SAP S/4HANA Connectivity

The SAP S/4HANA Connector (F-A2) is a separate feature that uses **OData v4** and **RFC/IDOC** protocols. It requires network-level access to the SAP landscape and pre-configured firewall rules and trust relationships before authentication can proceed. This is unrelated to the Salesforce Connector's payload size configuration.

### Authentication Requirements

Authentication for the Salesforce Connector requires:
- OAuth 2.0 Bearer Token with `workspace-admin` role and `connectors:write` scope (per [$[Connector Configuration API — Reference]$])
- Salesforce user with `Customize Application` and `Manage Connected Apps` permissions
- Object-level CRUD permissions on target objects

**In summary**: The available documentation does not provide a specific "Payload Size" configuration option for the Salesforce Connector. The only payload-related finding is the known bug (DPLAT-DEF-09) where attachments over 5MB are silently dropped. If payload size configuration is required, it may need to be addressed through the attachment size limitation bug or by consulting additional documentation not provided in these sources.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)

## Retries

The Salesforce Connector implements a multi-layered retry strategy that is automatically configured and requires minimal manual intervention. Here is how retries work for the specific error scenarios:

### Error Handling & Retry Logic

Per the [$[Salesforce Connector — Business Rules]$], the connector applies different retry behaviors depending on the error type:

| Error Type | Retry Behavior |
|------------|----------------|
| **API 4xx (client error)** | Retry 2 times with exponential backoff, then quarantine the record |
| **API 5xx (server error)** | Retry 5 times over 15 minutes, then alert the admin |
| **Rate limit (429)** | Throttle and queue; resume when the `X-RateLimit-Reset` header allows |
| **Network timeout** | Retry 3 times; mark record as `SYNC_PENDING` |

Quarantined records are retained for 7 days and can be manually reprocessed via the Connector UI.

### OAuth Token Refresh Retries

For authentication-related retries, the connector follows the logic defined in [$[DPLAT-003]$]:

- **Silent refresh**: The connector attempts a token refresh 5 minutes before the access token expires.
- **Exponential backoff**: Failed refresh attempts use the formula `min(initialDelay * 2^(attempt-1), maxDelay)` with 10% jitter. The configuration is:
  - Initial delay: 30 seconds
  - Maximum attempts: 5
  - Maximum delay: 5 minutes (300 seconds)
- **Alerting**: After 3 consecutive refresh failures, an alert is sent to the workspace-admin via the Connector Health Monitor.

### SAP S/4 Connectivity (Related)

For SAP S/4 connectivity, retry behavior is specified in [$[DPLAT-REQ-13]$] and [$[DPLAT-REQ-04]$]:

- **Automatic retry logic**: Both SOAP and OData v4 transports implement 3 retry attempts with exponential backoff for transient network failures.
- **Throughput retries**: The SAP connector sustains 5,000 records per minute with automatic retry on transient failures (maximum 3 retries) and 99.9% uptime during sync windows.

### Authentication Requirements

The Salesforce Connector uses **OAuth 2.0** with the following requirements (per [$[Salesforce Connector — Business Rules]$]):

1. **Connected App**: A DPLAT-managed Connected App must be created in the target Salesforce org with callback URL `https://connect.dplat.io/oauth/salesforce/callback`
2. **OAuth Scopes**: `api`, `refresh_token`, and `webhook` (for real-time sync)
3. **IP Allowlist**: DPLAT outbound IP ranges must be added to Salesforce Network Access settings (documented in DPLAT-DEF-02)
4. **User Permissions**: The Salesforce user must have `Customize Application`, `Manage Connected Apps`, and object-level CRUD permissions

### Summary

To configure retries for the Salesforce Connector, you do not need to set explicit retry parameters — the system applies the default retry policies automatically. The only configurable aspect is the **sync frequency** (near real-time, hourly batch, or daily batch), which indirectly affects how quickly retries are attempted. For OAuth token issues, the retry logic is fully automated with exponential backoff and admin alerting after 3 failures.

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)

## Backup & Recovery

### Primary: Configuring the Salesforce Connector for Backup & Recovery

To configure the Salesforce Connector with a focus on backup and recovery, workspace admins must complete the following steps:

**1. Prerequisites**
- Add DPLAT outbound IP ranges to your Salesforce org's Network Access settings (per [$[Salesforce Connector — Business Rules]$]):
  - `203.0.113.0/24` (US-East Primary)
  - `198.51.100.0/24` (EU-West Failover)
- Ensure the Salesforce user has `Customize Application`, `Manage Connected Apps`, and object-level CRUD permissions
- Create a DPLAT-managed Connected App in Salesforce with callback URL `https://connect.dplat.io/oauth/salesforce/callback` and OAuth scopes: `api`, `refresh_token`, `webhook`

**2. Authentication Setup**
The connector uses **OAuth 2.0** via the Salesforce Connected App flow (per [$[Salesforce Connector — Business Rules]$]):
- Initiate connector setup → redirected to Salesforce login
- Grant permissions via OAuth consent screen
- DPLAT receives authorization code and exchanges it for access + refresh tokens
- Tokens are stored encrypted in the tenant's secure vault
- Access tokens auto-refresh before 60-minute TTL expiration

**3. Connector Configuration via API**
Using the Connector Configuration API (per [$[Connector Configuration API — Reference]$]):
```json
POST /api/v1/connectors
{
  "name": "Salesforce Production",
  "type": "salesforce",
  "data_source": {
    "instance_url": "https://myorg.salesforce.com",
    "api_version": "v58.0"
  },
  "sync_schedule": "0 */30 * * *",
  "retention_days": 90,
  "pii_handling": {
    "masking_enabled": true,
    "excluded_fields": ["SSN", "credit_card"]
  }
}
```
- **`retention_days`** is critical for backup: default is 30 days, configurable up to 90 days for compliance
- Cached data is encrypted at rest using AES-256 and never exposed outside the tenant boundary

**4. Sync Frequency Options for Recovery**
Three modes are available (per [$[Salesforce Connector — Business Rules]$]):
- **Near real-time (webhook-driven)**: <5 second latency, for critical data
- **Scheduled batch (hourly)**: Full delta sync every hour
- **Scheduled batch (daily)**: Full snapshot at midnight UTC, lowest API consumption

For backup purposes, using **hourly batch** for delta sync combined with **daily full snapshots** provides a reliable recovery point.

**5. Error Handling & Recovery**
The connector implements automatic retry logic (per [$[Salesforce Connector — Business Rules]$]):
- API 4xx errors: 2 retries with exponential backoff, then quarantine
- API 5xx errors: 5 retries over 15 minutes, then alert admin
- Rate limits (429): Throttle and queue
- Network timeout: 3 retries; mark record as `SYNC_PENDING`
- Quarantined records retained for 7 days for manual reprocessing

**Important Recovery Note**: Per [$[DPLAT-DEF-15]$], after a Salesforce-side outage, automatic recovery currently takes approximately **4 hours** instead of the expected 60-minute SLA. A manual restart of the connector service reduces recovery time to ~15 minutes.

### Related: SAP S/4 Connectivity Setup

For SAP S/4HANA connectivity (per [$[DPLAT-004]$] and [$[DPLAT-REQ-13]$]):
- The setup wizard has 4 steps: Connection Details, Authentication, Schema Selection, and Review & Connect
- Supports both **SOAP** (with WS-Security 1.1 and X.509 certificates) and **OData v4** transport protocols
- Authentication supports SAP Cloud Identity Services and on-premise certificate-based options
- For backup/recovery: the connector must sustain 5,000 records/minute throughput (per [$[DPLAT-REQ-04]$]) and handle large result sets via paging with configurable page size (500-10,000 records) and stream processing (per [$[DPLAT-012]$])

### Authentication Requirements Summary

| Connector | Authentication Method | Key Requirements |
|-----------|----------------------|------------------|
| Salesforce | OAuth 2.0 (Connected App) | IP allowlist, OAuth scopes: `api`, `refresh_token`, `webhook` |
| SAP S/4HANA | SOAP: X.509 certificates; OData: SAP Cloud Identity Services | Certificate upload for on-premise; cloud identity for cloud instances |

For backup and recovery purposes, ensure **refresh tokens** are properly configured for Salesforce (they auto-refresh before 60-minute TTL) and that SAP connectors have proper retry logic (3 attempts with exponential backoff) to handle transient failures during recovery operations.

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)

## Config Export

# Config Export: Salesforce Connector Configuration

## How to Configure the Salesforce Connector

To configure the Salesforce Connector for the "Config Export" aspect, you need to complete the following steps:

### Prerequisites

Before configuration begins, ensure these prerequisites are met:

1. **IP Allowlist**: Add DPLAT outbound IP ranges to your Salesforce org's Network Access settings (per [CONFLUENCE] [$[Salesforce Connector — Business Rules]$]):
   - `203.0.113.0/24` (US-East Primary)
   - `198.51.100.0/24` (EU-West Failover)

2. **Salesforce User Permissions**: The user performing OAuth setup must have:
   - `Customize Application` permission
   - `Manage Connected Apps` permission
   - Object-level CRUD on target objects

3. **Connected App Configuration**: Create a DPLAT-managed Connected App in Salesforce:
   - Enable OAuth Settings
   - Set callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
   - Configure OAuth scopes: `api`, `refresh_token`, `webhook`

### Authentication Setup

The Salesforce Connector uses **OAuth 2.0** authentication (per [CONFLUENCE] [$[Salesforce Connector — Business Rules]$]):

1. Initiate connector setup via the Connector UI or API
2. You are redirected to Salesforce login for OAuth consent
3. DPLAT receives an authorization code and exchanges it for access + refresh tokens
4. Tokens are stored encrypted (AES-256-GCM) in the tenant's secure vault
5. Access tokens auto-refresh before expiration (60-minute TTL)

### Configuration via API

For programmatic "Config Export," use the Connector Configuration API (per [CONFLUENCE] [$[Connector Configuration API — Reference]$]):

**Create Connector:**
```json
POST /api/v1/connectors
{
  "name": "Salesforce Production",
  "type": "salesforce",
  "data_source": {
    "instance_url": "https://myorg.salesforce.com",
    "api_version": "v58.0"
  },
  "sync_schedule": "0 */30 * * *",
  "retention_days": 90,
  "pii_handling": {
    "masking_enabled": true,
    "excluded_fields": ["SSN", "credit_card"]
  }
}
```

**Update Configuration:**
```json
PUT /api/v1/connectors/{id}/config
{
  "sync_schedule": "0 */15 * * *",
  "retention_days": 120
}
```

### Authentication Requirements

| Requirement | Value |
|-------------|-------|
| Authentication Method | OAuth 2.0 Bearer Token |
| Required Role | `workspace-admin` |
| API Scope | `connectors:write` |
| Token Encryption | AES-256-GCM at rest |

## How to Set Up SAP S/4 Connectivity

The SAP S/4HANA Connector (feature F-A2) requires (per [CONFLUENCE] [$[Connector Framework — Module Overview]$]):

- **Network-level access** to the SAP landscape
- **Firewall rules and trust relationships** configured by tenant administrators before workspace admin authentication
- Support for **OData v4** (standard CDS views) and **RFC/IDOC** protocols
- **Pre-built mappings** for Finance, Sales, and Materials Management modules

Note: SAP S/4 connectivity is a separate connector from Salesforce and requires its own configuration workflow managed by tenant administrators.

## Config Export Summary

For the "Config Export" subsection specifically, the configuration can be exported programmatically via the Connector Configuration API. All configuration changes are recorded in the audit log with timestamp, actor, and diff. The configuration lifecycle progresses through four states: **Draft → Validated → Active → Retired** (per [CONFLUENCE] [$[Connector Framework — Architecture Deep-Dive]$]).

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-017] Salesforce — bulk migration tool from legacy v1 connector](https://demo-jira.local/browse/DPLAT-017)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-DEF-09] Salesforce — sync drops attachments larger than 5MB](https://demo-jira.local/browse/DPLAT-DEF-09)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)

## Rollback

The Salesforce Connector does **not** have a dedicated "Rollback" feature or configuration option in the provided documentation. However, the rollback capability can be understood and configured through the following mechanisms:

### How to Configure the Salesforce Connector (Rollback-Relevant Aspects)

1. **Retention of Cached Data (Primary Rollback Mechanism)**
   - The connector maintains a local cache of synced records with a **default retention period of 30 days** (configurable up to 90 days for compliance requirements) per [$[Salesforce Connector — Business Rules]$].
   - Cached data includes full record snapshots, change tracking metadata, and relationship pointers, all encrypted at rest using AES-256.
   - To configure: Workspace admins can set `retention_days` in the Connector Configuration API (up to 90 days) as shown in the [$[Connector Configuration API — Reference]$]:
     ```json
     {
       "retention_days": 90,
       "pii_handling": {
         "masking_enabled": true
       }
     }
     ```

2. **Quarantine and Manual Reprocessing**
   - When sync errors occur (e.g., API 4xx errors), records are quarantined and retained for **7 days** per [$[Salesforce Connector — Business Rules]$].
   - Quarantined records can be manually reprocessed via the Connector UI, effectively serving as a rollback point for failed sync operations.

3. **Error Handling with Retry Logic**
   - The connector implements automatic retry with exponential backoff for transient failures (5 retries over 15 minutes for 5xx errors, 2 retries for 4xx errors) per [$[Salesforce Connector — Business Rules]$].
   - This provides a safety net that prevents the need for manual rollback in most cases.

### SAP S/4 Connectivity (Related Context)

For SAP S/4 connectivity, the rollback-related mechanisms include:
- **Checkpoint-based resumption**: For large extraction jobs (>100,000 records), the SAP connector writes progress checkpoints every 10,000 records to the audit log, enabling job resumption from the last checkpoint in case of failure (per [$[DPLAT-012]$]).
- **Automatic retry**: Both SOAP and OData v4 transports include automatic retry logic (3 attempts, exponential backoff) for transient network failures (per [$[DPLAT-REQ-13]$]).

### Authentication Requirements (Rollback-Relevant)

- **OAuth 2.0 with token refresh**: The Salesforce connector automatically refreshes access tokens 5 minutes before expiry. If refresh fails after 3 consecutive attempts, the workspace admin is alerted via the Connector Health Monitor (per [$[DPLAT-003]$]).
- **Token encryption**: All OAuth tokens are encrypted at rest using AES-256-GCM in the tenant's secure credential store (per [$[DPLAT-003]$]).

### Key Limitation

The documentation does **not** describe a point-in-time rollback or snapshot restoration feature. The rollback capability is limited to:
- Reprocessing quarantined records (7-day window)
- Restoring from cached data (30-90 day retention)
- Resuming from checkpoints (SAP only)

For a true rollback to a previous state, workspace admins would need to rely on the cached data retention period and manually re-sync from that cache.

**Sources:**
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)

## State Management

The Salesforce Connector's state management revolves around **OAuth 2.0 token lifecycle management**, **sync state tracking**, and **cached data retention**. Here is how to configure each aspect:

### 1. OAuth Token State Management

The connector uses OAuth 2.0 with automatic token refresh to maintain continuous connectivity. Per [$[DPLAT-003]$], the connector performs a **silent token refresh 5 minutes before access token expiry** (60-minute TTL). The refresh logic implements exponential backoff: initial delay 30s, max 5 retries, capped at 5 minutes. After 3 consecutive failures, an alert is sent to the workspace admin via the Health Monitor.

**Configuration steps:**
- Tokens are stored encrypted at rest using AES-256-GCM in the tenant's secure vault (per [$[Salesforce Connector — Business Rules]$])
- To re-authenticate manually, navigate to **Connectors → Salesforce → Settings** and click **Re-authenticate** (per [$[Salesforce Connector — Troubleshooting Guide]$])
- Enable **Token Refresh Alerting** in connector settings for proactive notifications

### 2. Sync State and Checkpointing

The connector tracks sync state through **checkpointing** after each successful batch, enabling recovery from worker failures (per [$[Connector Framework — Architecture Deep-Dive]$]). The sync execution model uses lease-based task assignment with 30-second lease renewal intervals.

**Configuration options:**
- **Sync frequency modes** (per [$[Salesforce Connector — Business Rules]$]):
  - Near real-time (webhook-driven, <5s latency) — default for standard objects
  - Scheduled batch hourly — default for custom objects
  - Scheduled batch daily
- Override per-object via the Connector Configuration UI
- For large objects (>100K records), enable **incremental sync** to manage API rate limits (per [$[Salesforce Connector — Troubleshooting Guide]$])

### 3. Cached Data Retention

The connector maintains a local cache of synced records. **Default retention is 30 days**, after which records are automatically purged. Workspace admins can configure extended retention up to **90 days** for compliance requirements (subject to additional storage costs). Configure via the Connector Configuration API or UI.

### 4. Authentication Requirements for State Management

To establish the initial state, you must complete the OAuth 2.0 Connected App flow (per [$[Salesforce Connector — Business Rules]$]):

1. Create a DPLAT-managed Connected App in Salesforce with callback URL `https://connect.dplat.io/oauth/salesforce/callback`
2. Required OAuth scopes: `api`, `refresh_token`, `webhook`
3. The Salesforce user must have `Customize Application` and `Manage Connected Apps` permissions
4. Add DPLAT outbound IP ranges to Salesforce Network Access settings:
   - US-East: `203.0.113.0/24`
   - EU-West: `198.51.100.0/24`

### 5. SAP S/4HANA Connectivity (Related)

While not part of the Salesforce connector, the SAP S/4HANA connector (F-A2) uses **OData v4** and **RFC/IDOC** protocols with its own state management. It requires network-level access and firewall rules configured by tenant administrators before workspace admins can authenticate (per [$[Connector Framework — Module Overview]$]).

### Summary of Key State Management Configuration

| Aspect | Configuration Point | Default |
|--------|-------------------|---------|
| Token refresh timing | Automatic 5 min before expiry | 60-min TTL |
| Retry policy | Exponential backoff (30s–300s) | 5 max attempts |
| Cache retention | Configurable (30–90 days) | 30 days |
| Sync mode | Per-object override | Real-time (standard), hourly (custom) |
| Health monitoring | Token refresh alerts | Enabled via settings |

**Sources:**
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-017] Salesforce — bulk migration tool from legacy v1 connector](https://demo-jira.local/browse/DPLAT-017)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)

## Disaster Recovery

For the **Disaster Recovery** subsection of "Configuration Management" under feature F-A1 (Salesforce Connector), the following configuration guidance applies:

### Salesforce Connector Configuration for Disaster Recovery

**IP Allowlist Requirements (Critical for DR Failover)**

Per [$[Salesforce Connector — Business Rules]$], the connector requires specific DPLAT outbound IP addresses to be allowlisted in your Salesforce org's Network Access settings. For disaster recovery scenarios, **both primary and failover IP ranges must be configured in advance**:

- **Primary (US-East)**: `203.0.113.0/24`
- **Failover (EU-West)**: `198.51.100.0/24`

Failure to pre-configure the failover IP range will cause connection timeouts during DR failover, as documented in [$[Salesforce Connector — Troubleshooting Guide]$] (symptom: "Connection timeout" or "Access denied from IP").

**Authentication Resilience**

The connector uses **OAuth 2.0** with refresh tokens. For DR readiness:
- Ensure the Salesforce Connected App is configured with the callback URL `https://connect.dplat.io/oauth/salesforce/callback`
- Tokens are stored encrypted in the tenant's secure vault and auto-refresh before expiration (60-minute TTL)
- If token refresh fails during DR, use the **Re-authenticate** option in Connector Settings (per [$[Salesforce Connector — Troubleshooting Guide]$])

**Recovery Time Objective (RTO) Consideration**

A critical known issue exists: according to [$[DPLAT-DEF-15]$], the connector recovery after a Salesforce-side outage actually takes **~4 hours (240 minutes)** instead of the expected 30-60 minute SLA. The documented workaround is a **manual restart of the connector service**, which reduces recovery time to ~15 minutes. For unattended DR environments, this defect must be addressed before relying on automatic recovery.

**Sync Configuration for DR**

Configure the connector via the Connector Configuration API (`POST /api/v1/connectors`) with:
- `sync_schedule`: Use cron expression (e.g., `"0 */30 * * *"` for 30-minute intervals)
- `retention_days`: Set to 90 days for compliance (default is 30 days)
- `pii_handling.masking_enabled`: Set to `true` for compliance

### SAP S/4 Connectivity Setup

For SAP S/4HANA connectivity in a DR context:

**Transport Protocols**: The connector supports both **SOAP** (with WS-Security 1.1 and X.509 certificate authentication) and **OData v4** (with batch operations of ≥50 requests per batch), per [$[DPLAT-REQ-13]$].

**Throughput Requirements**: The connector must sustain **5,000 records per minute** during full sync with ≤200ms latency per record (p95), as specified in [$[DPLAT-REQ-04]$].

**Large Dataset Handling**: For DR scenarios involving large data volumes, configure `page_size` (default 2000, range 500-10000) in the connector definition YAML. The connector automatically uses server-side paging for results exceeding 10,000 records and writes progress checkpoints every 10,000 records for job resumption (per [$[DPLAT-012]$]).

**Known DR Risks**:
- **Encoding issues**: German umlauts (ä, ö, ü, ß) in CHAR fields may return null ([$[DPLAT-DEF-11]$]) — apply post-processing transformations as a workaround
- **Delta sync gaps**: Records updated within 1 second of the last cursor may be skipped ([$[DPLAT-DEF-12]$]) — run periodic full syncs to reconcile

### Authentication Requirements Summary

| Connector | Method | Key Requirements |
|-----------|--------|------------------|
| Salesforce | OAuth 2.0 | Scopes: `api`, `refresh_token`, `webhook`; IP allowlisting required |
| SAP S/4 | SOAP (X.509 certs) or OData v4 | Supports SAP Cloud Identity Services or on-premise certificate-based auth |

**For DR readiness, pre-configure both primary and failover IP ranges, test token refresh mechanisms, and account for the known 4-hour recovery delay by planning manual restart procedures or scheduling maintenance windows.**

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-15] Connector recovery actually takes ~4 hours after Salesforce-side outage](https://demo-jira.local/browse/DPLAT-DEF-15)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Operations Runbook](https://demo-confluence.local/wiki/spaces/DPLAT/pages/85c7440082c0)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-REQ-15] Connector recovery — operational runbook target is 30 minutes](https://demo-jira.local/browse/DPLAT-REQ-15)
