# 2.1  Setting up the Salesforce connector

_Feature: `F-A1` · Audience: end-user, workspace-admin_

> Configure Salesforce data sync

## Prerequisites

## Prerequisites for Setting Up the Salesforce Connector (F-A1)

To connect Salesforce as part of feature F-A1, the following prerequisites must be completed before configuring the connector:

### 1. IP Allowlist Configuration
Per [$[Salesforce Connector — Business Rules]$] and [$[DPLAT-DEF-02]$], the DPLAT outbound IP addresses must be allowlisted in the target Salesforce org's **Network Access** settings. The required IP ranges are:

- **DPLAT US-East (Primary):** `203.0.113.0/24`
- **DPLAT EU-West (Failover):** `198.51.100.0/24`

This is a critical step — if omitted, the setup wizard may appear to succeed but subsequent sync jobs will fail with "connection timeout" errors (as documented in [$[DPLAT-DEF-02]$]). Request the full IP allowlist documentation via the tenant support portal.

### 2. Required Salesforce User Permissions
The Salesforce user performing the OAuth setup must have the following permissions in the target org:
- `Customize Application` permission
- `Manage Connected Apps` permission
- Object-level CRUD permissions on target objects (Account, Contact, Opportunity, etc.)

### 3. Connected App Configuration
A DPLAT-managed Connected App must be created in the Salesforce org:
1. Navigate to **Setup → App Manager → New Connected App**
2. Enable **"Enable OAuth Settings"**
3. Add the callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
4. Set the required OAuth scopes: `api`, `refresh_token`, and `webhook` (for real-time sync)

### 4. Credentials Needed for F-A1
During the setup wizard (implemented in [$[DPLAT-002]$]), the workspace admin must provide:
- **Client ID** and **Client Secret** (from the Connected App)
- **Refresh Token** (obtained after initial OAuth authorization)

These credentials are entered through a secure form with input validation. After submission, the wizard performs an OAuth token exchange to validate the connection.

### 5. Authorization Flow
The authorization process follows the **OAuth 2.0** flow:
1. The workspace admin initiates connector setup and is redirected to the Salesforce login page
2. The user grants permissions via the Salesforce OAuth consent screen
3. DPLAT receives an authorization code and exchanges it for an access token + refresh token
4. Tokens are stored encrypted at rest using AES-256-GCM in the tenant's secure vault (per [$[DPLAT-REQ-03]$])
5. Access tokens are automatically refreshed 5 minutes before expiry (60-minute TTL), as implemented in [$[DPLAT-003]$]

**Note:** If the Salesforce org has a restricted IP allowlist, the wizard currently does not detect this during the connection test (see [$[DPLAT-DEF-02]$]). The workaround is to manually add the DPLAT IP ranges to the org's Network Access settings before running the wizard.

**Sources:**
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Connection Steps

## Connection Steps for the Salesforce Connector (F-A1)

To connect Salesforce using the connector framework, follow these steps as a workspace admin:

### Step 1: Prerequisites
Before starting the wizard, ensure the following prerequisites are met:
- **IP Allowlist**: Add DPLAT outbound IP ranges (`203.0.113.0/24` for US-East and `198.51.100.0/24` for EU-West) to your Salesforce org's **Setup → Security → Network Access** settings (per [$[Salesforce Connector — Business Rules]$]).
- **Salesforce User Permissions**: The user performing setup must have `Customize Application`, `Manage Connected Apps`, and object-level CRUD permissions on target objects (Account, Contact, etc.).
- **Connected App**: A DPLAT-managed Connected App must exist in your Salesforce org with OAuth enabled, callback URL `https://connect.dplat.io/oauth/salesforce/callback`, and scopes `api`, `refresh_token`, and `webhook`.

### Step 2: Launch the Setup Wizard
Navigate to the **Connectors** page and click **Add Connector**, then select **Salesforce** from the list (per [$[DPLAT-002]$]).

### Step 3: Enter Credentials
In the secure form, enter the following credentials (per [$[DPLAT-002]$]):
- **Client ID** (from the Connected App)
- **Client Secret** (from the Connected App)
- **Refresh Token** (obtained after initial OAuth authorization)

### Step 4: OAuth Authorization
Click **Connect** to initiate the OAuth 2.0 flow (per [$[Salesforce Connector — Business Rules]$]):
1. You are redirected to the Salesforce login page.
2. Grant permissions via the Salesforce OAuth consent screen.
3. DPLAT receives an authorization code and exchanges it for an access token + refresh token.
4. Tokens are encrypted at rest using AES-256-GCM in the tenant's secure vault (per [$[DPLAT-REQ-03]$]).

**Note**: After completing OAuth, the wizard may lose browser focus (known issue [$[DPLAT-DEF-10]$]). Manually switch back to the original wizard tab if needed.

### Step 5: Connection Validation
The wizard validates the connection by performing an OAuth token exchange (per [$[DPLAT-002]$]):
- **Success**: A green checkmark appears.
- **Failure**: A user-friendly error message is displayed.

**Important**: The wizard may show success even if the Salesforce org has a restricted IP allowlist (known issue [$[DPLAT-DEF-02]$]). If subsequent syncs fail with "connection timeout," verify the IP allowlist configuration.

### Step 6: Select Objects to Sync
Choose which Salesforce objects to sync (e.g., Account, Opportunity) with a preview of available fields (per [$[DPLAT-002]$]).

### Step 7: Complete Setup
Upon completion, the connector appears in the **Connector Health Monitor** with status **Active** and shows the last sync timestamp (per [$[DPLAT-002]$]).

### Credentials Needed for F-A1
- **Client ID** and **Client Secret** from the DPLAT-managed Connected App in Salesforce.
- **Refresh Token** obtained during OAuth authorization.
- **OAuth Scopes**: `api`, `refresh_token`, `webhook` (per [$[Salesforce Connector — Business Rules]$]).

### How to Authorize the Salesforce Connector
Authorization uses the **OAuth 2.0** flow via the Salesforce Connected App (per [$[Salesforce Connector — Business Rules]$]):
1. The wizard redirects you to Salesforce login.
2. You grant permissions on the OAuth consent screen.
3. DPLAT exchanges the authorization code for access and refresh tokens.
4. Tokens are stored encrypted and automatically refreshed 5 minutes before expiry (per [$[DPLAT-003]$]).

**Sources:**
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Authentication Setup

## Authentication Setup for the Salesforce Connector (F-A1)

To connect Salesforce to the Data Platform, the connector uses **OAuth 2.0** authentication via the Salesforce Connected App flow, as documented in [$[Salesforce Connector — Business Rules]$] and referenced in [$[DPLAT-003]$] and [$[DPLAT-REQ-03]$].

### How to Connect Salesforce

The connection process follows a guided setup wizard (implemented in [$[DPLAT-002]$]) with these steps:

1. **Initiate the wizard**: The workspace admin navigates to the Connectors page and selects "Add Connector" → "Salesforce."
2. **Enter credentials**: The admin provides the Salesforce **Client ID**, **Client Secret**, and **Refresh Token** through a secure form with input validation (per [$[DPLAT-002]$]).
3. **OAuth redirect**: The admin is redirected to the Salesforce login page to grant permissions via the Salesforce OAuth consent screen.
4. **Token exchange**: DPLAT receives an authorization code and exchanges it for an access token and refresh token. Tokens are stored encrypted in the tenant's secure vault using AES-256-GCM with per-tenant encryption keys (per [$[DPLAT-REQ-03]$]).
5. **Connection validation**: The wizard validates the connection by performing an OAuth token exchange and displays success or failure status (per [$[DPLAT-002]$]).
6. **Completion**: Upon success, the connector appears in the Connector Health Monitor with status "Active."

### Required Credentials for F-A1

The following credentials and configurations are needed:

- **Client ID** and **Client Secret** — from a DPLAT-managed Connected App created in the target Salesforce org
- **Refresh Token** — obtained during the OAuth consent flow
- **Callback URL** — must be set in the Connected App: `https://connect.dplat.io/oauth/salesforce/callback`
- **OAuth Scopes** — must include: `api` (full API access), `refresh_token` (long-lived refresh capability), and `webhook` (Platform Events subscription for real-time sync)

Additionally, the Salesforce user performing OAuth setup must have `Customize Application` and `Manage Connected Apps` permissions, plus object-level CRUD on target objects (per [$[Salesforce Connector — Business Rules]$]).

### How to Authorize the Salesforce Connector

Authorization is handled automatically through the OAuth 2.0 flow:

1. The workspace admin initiates connector setup and is redirected to Salesforce login.
2. The user grants permissions via the Salesforce OAuth consent screen.
3. DPLAT receives the authorization code and exchanges it for an access token + refresh token.
4. Tokens are stored encrypted in the tenant's secure vault (AES-256-GCM, per [$[DPLAT-REQ-03]$]).
5. The connector automatically refreshes access tokens **5 minutes before expiry** (60-minute TTL) using the stored refresh token, with exponential backoff retry logic (initial delay 30s, max 5 retries, cap at 5 minutes) as implemented in [$[DPLAT-003]$].
6. After 3 consecutive refresh failures, an alert is sent to the workspace admin via the Connector Health Monitor.

### Important Prerequisites

Before starting authentication, the workspace admin must ensure:

- **IP Allowlist**: DPLAT outbound IP ranges (`203.0.113.0/24` for US-East, `198.51.100.0/24` for EU-West) must be added to the Salesforce org's Network Access settings. Failure to do this causes silent connection test success but subsequent sync failures with "connection timeout" errors (documented in [$[DPLAT-DEF-02]$]).
- **Connected App**: A DPLAT-managed Connected App must be created in the target Salesforce org with OAuth settings enabled and the correct callback URL configured (per [$[Salesforce Connector — Business Rules]$]).

### Known Issue

There is a known bug ([$[DPLAT-DEF-10]$]) where after completing OAuth authentication, the browser window/tab used for the wizard loses focus, causing user confusion. The workaround is to manually switch back to the original wizard tab after completing Salesforce login.

**Sources:**
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Data Mapping

## Data Mapping for the Salesforce Connector (F-A1)

### How to Connect Salesforce

To connect Salesforce for the Data Mapping aspect of feature F-A1, workspace admins use the **Connector Configuration UI** or the **Connector Configuration API**. The connection process involves:

1. **OAuth 2.0 Authentication**: The Salesforce Connector uses OAuth 2.0 via a Salesforce Connected App flow. The workspace admin initiates connector setup and is redirected to Salesforce login, grants permissions via the OAuth consent screen, and DPLAT receives an authorization code which is exchanged for access + refresh tokens (per [$[Salesforce Connector — Business Rules]$]).

2. **Object Selection**: During setup, the admin selects which Salesforce objects to sync (Account, Opportunity, etc.) with a preview of available fields (per [$[DPLAT-002]$]).

3. **Field Mapping Configuration**: After initial connection, the admin accesses a **field-mapping configuration screen** from the Salesforce Connector settings. This screen displays all detected custom objects with their API names. For each custom object, the admin can create, edit, and delete field mappings between Salesforce fields and platform data model fields using a two-column interface with search functionality (per [$[DPLAT-016]$]).

### Credentials Needed for F-A1

The following credentials are required for the Salesforce connector setup:

- **Client ID** — from the Salesforce Connected App
- **Client Secret** — from the Salesforce Connected App
- **Refresh Token** — obtained during OAuth flow
- **OAuth Scopes**: `api` (full API access), `refresh_token` (long-lived refresh), `webhook` (Platform Events subscription for real-time sync)

These credentials are entered through a secure form with input validation and stored encrypted at rest using AES-256-GCM in the tenant's secure vault (per [$[Salesforce Connector — Business Rules]$] and [$[DPLAT-002]$]).

### How to Authorize the Salesforce Connector

The authorization flow works as follows:

1. The workspace admin initiates connector setup and is redirected to Salesforce login
2. The user grants permissions via the Salesforce OAuth consent screen
3. DPLAT receives the authorization code and exchanges it for an access token + refresh token
4. Tokens are stored encrypted in the tenant's secure vault
5. Access tokens are automatically refreshed 5 minutes before expiry (60-minute TTL) using exponential backoff retry logic (initial delay 30s, max 5 retries, cap at 5 minutes)

**Important prerequisite**: The Salesforce user performing OAuth setup must have `Customize Application`, `Manage Connected Apps` permissions, and object-level CRUD on target objects. Additionally, DPLAT outbound IP addresses must be allowlisted in the target Salesforce org's Network Access settings (per [$[Salesforce Connector — Business Rules]$] and [$[DPLAT-DEF-02]$]).

### Data Mapping Specifics

For the Data Mapping subsection specifically:

- **Standard objects** (Account, Contact, Lead, Opportunity, Case) have out-of-the-box field mappings
- **Custom objects** require explicit schema registration via the Connector Configuration API, where workspace admins define field mappings and transformation rules before enabling sync
- The system validates that each platform data model field is mapped to at most one Salesforce field per custom object, displaying a clear error message for duplicate mappings
- After saving field mappings, the next connector sync operation applies the custom mappings and logs the transformation in the audit log with a summary of mapped records
- The connector supports **selective field mapping** to reduce PII exposure at the source (per [$[Connector Framework — Module Overview]$])

**Sources:**
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Verification

## Verification: How to Connect Salesforce (Feature F-A1)

To connect Salesforce and verify the connection for feature F-A1, follow these steps based on the setup wizard implementation in [$[DPLAT-002]$]:

### Primary Connection Process

1. **Initiate the wizard**: Navigate to the Connectors page and click "Add Connector", then select "Salesforce" from the connector list.

2. **Enter credentials**: Provide the following credentials through the secure form (per [$[DPLAT-002]$] acceptance criteria):
   - **Client ID** (from your Salesforce Connected App)
   - **Client Secret** (from your Salesforce Connected App)
   - **Refresh Token** (obtained during initial OAuth flow)

3. **OAuth authentication**: The wizard redirects you to the Salesforce login page. After completing authentication, Salesforce returns an authorization code, which DPLAT exchanges for an access token and refresh token (per [$[Salesforce Connector — Business Rules]$]).

4. **Connection validation**: The wizard performs an OAuth token exchange and displays a success or failure status. According to [$[DPLAT-002]$], QA testing confirmed that "connection validation correctly handles invalid credentials with user-friendly error message."

### Credentials Required for F-A1

Based on the documentation, the following are needed:

| Credential | Source | Purpose |
|------------|--------|---------|
| **Client ID** | Salesforce Connected App | Identifies the application to Salesforce |
| **Client Secret** | Salesforce Connected App | Authenticates the application |
| **Refresh Token** | OAuth flow | Enables long-lived access without re-authentication |
| **Instance URL** | Your Salesforce org | e.g., `https://myorg.salesforce.com` |

Additionally, the Salesforce user performing setup must have `Customize Application` and `Manage Connected Apps` permissions (per [$[Salesforce Connector — Business Rules]$]).

### Authorization Flow

The authorization process follows the **OAuth 2.0** flow as documented in [$[Salesforce Connector — Business Rules]$]:

1. The workspace admin initiates connector setup and is redirected to Salesforce login
2. User grants permissions via the Salesforce OAuth consent screen
3. DPLAT receives the authorization code and exchanges it for an access token + refresh token
4. Tokens are stored encrypted using AES-256-GCM in the tenant's secure vault (per [$[DPLAT-REQ-03]$])
5. Access tokens are automatically refreshed before expiration (60-minute TTL)

### Verification Steps

After completing the wizard, verify the connection by:

1. **Checking the Connector Health Monitor**: The connector should appear with status "Active" and show the last sync timestamp (per [$[DPLAT-002]$] acceptance criteria)
2. **Testing object selection**: Select which Salesforce objects to sync (Account, Opportunity) with a preview of available fields
3. **Confirming token refresh**: The connector automatically refreshes tokens 5 minutes before expiry, with exponential backoff retry logic (per [$[DPLAT-003]$])

### Known Issue

Note that there is an open bug [$[DPLAT-DEF-10]$] where browser focus may be lost after the OAuth redirect. The workaround is to manually switch back to the original wizard tab after completing Salesforce login.

**Sources:**
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)

## Troubleshooting (common)

## Troubleshooting: Setting Up the Salesforce Connector (F-A1)

### How to Connect Salesforce

Based on the troubleshooting documentation, the most common issue when connecting Salesforce is the **IP allowlist requirement**. According to [$[Salesforce Connector — Business Rules]$], DPLAT outbound IP addresses must be added to your Salesforce organization's **Network Access** settings before the connection can succeed. The required IP ranges are:

- **DPLAT US-East (Primary):** `203.0.113.0/24`
- **DPLAT EU-West (Failover):** `198.51.100.0/24`

If the connection test fails with `Connection timeout` or `Access denied from IP: X.X.X.X`, the root cause is almost always that these IP ranges have not been whitelisted. This is documented in DPLAT-DEF-02.

**Resolution steps:**
1. Contact your Salesforce admin to add the DPLAT IP range to **Setup → Security → Network Access**
2. Verify OAuth credentials are valid and not expired
3. Confirm your tenant's outbound firewall allows connections to DPLAT endpoints
4. Re-run the connection test in the setup wizard

**Workaround:** If IP whitelisting is not immediately possible, use the **OAuth Proxy Mode** which routes connections through your organization's outbound proxy.

### What Credentials Are Needed for F-A1?

Per [$[DPLAT-002]$], the setup wizard requires the following credentials:
- **Client ID**
- **Client Secret**
- **Refresh Token**

These are entered through a secure form with input validation. The wizard validates the Salesforce connection by performing an OAuth token exchange and displays success/failure status.

Additionally, the Salesforce user performing OAuth setup must have these permissions (per [$[Salesforce Connector — Business Rules]$]):
- `Customize Application` permission
- `Manage Connected Apps` permission
- Object-level CRUD on target objects (Account, Contact, etc.)

### How to Authorize the Salesforce Connector

The authorization follows the **OAuth 2.0** flow via a Salesforce Connected App. Per [$[Salesforce Connector — Business Rules]$]:

1. A DPLAT-managed Connected App must be created in the target Salesforce org
2. Navigate to **Setup → App Manager → New Connected App**
3. Enable "Enable OAuth Settings"
4. Add callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
5. Set OAuth scopes: `api`, `refresh_token`, `webhook`

**Known issue:** According to [$[DPLAT-DEF-10]$], after completing OAuth authentication, the browser window/tab used for the wizard may lose focus, causing confusion. The workaround is to manually switch back to the original wizard tab after completing Salesforce login.

**Critical bug:** Per [$[DPLAT-DEF-02]$], when connecting to a sandbox org with a restricted IP allowlist, the wizard may show a green checkmark indicating success, but subsequent data sync jobs fail with "connection timeout" errors. The wizard does not validate or warn about this prerequisite. **Always verify IP allowlist configuration before running the setup wizard.**

### Common Troubleshooting Summary

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| Connection timeout / Access denied | IP allowlist not configured | Add DPLAT IP ranges to Salesforce Network Access |
| 401 Unauthorized after setup | OAuth token refresh failed | Click **Re-authenticate** in Connector Settings |
| Wizard shows success but sync fails | Silent IP allowlist failure (sandbox) | Manually add IP ranges before setup |
| Browser focus lost after OAuth | Known UI bug (DPLAT-DEF-10) | Manually switch back to wizard tab |

**Sources:**
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-DEF-10] Salesforce — wizard browser focus lost after OAuth redirect](https://demo-jira.local/browse/DPLAT-DEF-10)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-018] Salesforce — sync error retry queue with dead-letter handling](https://demo-jira.local/browse/DPLAT-018)
- 📋 [[DPLAT-REQ-03] Salesforce OAuth token storage — AES-256 encryption at rest](https://demo-jira.local/browse/DPLAT-REQ-03)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
