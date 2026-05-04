# 2.2  Setting up the SAP S/4 connector

_Feature: `F-A2` · Audience: end-user, workspace-admin_

> Configure SAP S/4 data sync

## Prerequisites

`⚠ stale`

Before configuring the SAP S/4HANA connector, the following prerequisites must be met across network, authentication, and system levels.

### Network-Level Requirements

- **Network access to SAP landscape**: The connector requires network-level access to the SAP S/4HANA system. Tenant administrators must configure firewall rules and establish trust relationships before the workspace admin can authenticate (per [$[Connector Framework — Module Overview]$]).
- **Outbound connectivity**: Corporate firewalls must allow outbound connections from the DPLAT platform to SAP endpoints. This includes opening ports for RFC (typically 33xx) and HTTP/HTTPS (443) protocols.

### Authentication & Security Prerequisites

- **Certificate trusts**: TLS certificate trusts must be configured for secure communication. The connector supports both SAP Cloud Identity Services (cloud-based) and on-premise certificate-based authentication options (per [$[DPLAT-004]$]).
- **WS-Security 1.1**: For SOAP transport, X.509 certificate authentication is required (per [$[DPLAT-REQ-13]$]).
- **Tenant-level settings**: Tenant administrators must pre-configure network policies, proxy configuration, and global rate-limit defaults before workspace admins can proceed with connector setup (per [$[Connector Framework — Module Overview]$]).

### SAP System Requirements

- **SAP S/4HANA version**: The connector supports SAP S/4HANA systems with OData v4 and RFC protocols. For SAP ECC compatibility, version 6.0 or later is required (per [$[Release Notes — v2.4 (Planned)]$]).
- **Transport protocols**: Both SOAP and OData v4 transport must be enabled on the SAP system. OData v4 is used for standard CDS views and business objects; RFC/IDOC is used for legacy transactional data (per [$[Connector Framework — Module Overview]$] and [$[DPLAT-REQ-13]$]).
- **Performance baseline**: The SAP system must be capable of sustaining a minimum throughput of 5,000 records per minute during full synchronization operations (per [$[DPLAT-REQ-04]$]).

### How to Validate SAP Connectivity

The validation process occurs during the initial setup wizard, which consists of four steps: Connection Details, Authentication, Schema Selection, and Review & Connect (per [$[DPLAT-004]$]). To validate connectivity:

1. **Connection test**: After entering connection parameters (host, port, protocol), the wizard performs an inline validation check. This tests network reachability and protocol compatibility.
2. **Authentication verification**: The wizard validates credentials by performing an authentication handshake. For cloud-based auth, this uses SAP Cloud Identity Services; for on-premise, it validates the uploaded certificate.
3. **Schema discovery**: Upon successful authentication, the connector performs schema auto-discovery for SAP tables, structures, and CDS views. This confirms that the SAP system is accessible and that the configured user has appropriate permissions.
4. **Final connection test**: After completing all wizard steps, the connector runs a test connection. If successful, the connector appears in the workspace with status "Configured" (per [$[DPLAT-004]$]).

**Note**: If the connection test fails, common causes include incorrect firewall rules, expired certificates, or missing IP whitelisting. Tenant administrators should verify network policies and certificate trusts before retrying.

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)

## Connection Steps

Based on the available documentation, here are the specific connection steps for setting up the SAP S/4HANA connector, focusing on the "Connection Steps" aspect of feature F-A2.

### Prerequisites / Requirements

Before beginning the connection setup, ensure the following requirements are met:

1. **SAP System Version**: The SAP S/4HANA connector requires target system version 6.0 or later (per [$[Release Notes — v2.4 (Planned)]$]).
2. **Transport Protocols**: The connector supports both SOAP (with WS-Security 1.1 and X.509 certificate authentication) and OData v4 transport protocols (per [$[DPLAT-REQ-13]$]).
3. **Network Access**: Ensure outbound IP addresses are whitelisted in your SAP system's network access settings, similar to the Salesforce connector requirements documented in [$[Salesforce Connector — Troubleshooting Guide]$].
4. **Authentication Credentials**: Have either SAP Cloud Identity Services credentials or on-premise certificate-based authentication ready (per [$[DPLAT-004]$]).

### Connection Steps

The SAP S/4HANA connector setup wizard follows a 4-step guided process (per [$[DPLAT-004]$]):

**Step 1: Connection Details**
- Enter the SAP S/4HANA instance URL or host address
- Specify the API version (e.g., for OData v4 transport)
- Configure the transport protocol (SOAP or OData v4)
- Set the connection pool size (default: 10 connections per the connector-framework configuration in [$[connector-framework]$])

**Step 2: Authentication**
- Choose between SAP Cloud Identity Services (cloud-based) or on-premise certificate-based authentication
- For SOAP transport: configure WS-Security 1.1 with X.509 certificate authentication
- For OData v4: provide OAuth credentials as applicable
- Each step includes inline validation with clear error messages before allowing progression

**Step 3: Schema Selection**
- Select the SAP tables, structures, or CDS views to connect
- The connector supports schema auto-discovery for SAP data sources

**Step 4: Review & Connect**
- Review all configuration parameters
- Click "Connect" to establish the connection
- Upon completion, the connector appears in the workspace with status "Configured" and a test connection succeeds

### Validating SAP Connectivity

To validate the SAP connection after setup:

1. **Run a Connection Test**: The wizard includes a test connection feature that executes after configuration completion (per [$[DPLAT-004]$]).
2. **Verify Transport Health**: Connection health checks execute every 5 minutes with a maximum 30-second timeout per protocol (per [$[DPLAT-REQ-13]$]).
3. **Check Performance Baseline**: The connector should sustain a minimum of 5,000 records per minute during full synchronization operations (per [$[DPLAT-REQ-04]$]).
4. **Monitor for Common Issues**: Watch for connection timeouts or access denied errors, which typically indicate IP whitelisting or firewall issues (based on patterns from [$[Salesforce Connector — Troubleshooting Guide]$]).

### Additional Configuration Notes

- For large result sets (over 10,000 records), the connector automatically uses server-side paging with a configurable page size (default: 2,000 records per page) to prevent memory exhaustion (per [$[DPLAT-012]$]).
- The connector supports both SOAP and OData v4 transport protocols with automatic retry logic (3 attempts with exponential backoff) for transient network failures (per [$[DPLAT-REQ-13]$]).
- Environment variables such as `METATRON_API_ENDPOINT` and `AMISOL_DPLAT_CONNECTION_POOL_SIZE` can be configured to customize connector behavior (per [$[connector-framework]$]).

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-023] SAP — legacy SAP ECC 6.0 compatibility mode](https://demo-jira.local/browse/DPLAT-023)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)

## Security Protocol

### Primary Question: How to Setup SAP S/4?

Setting up the SAP S/4HANA connector involves a guided 4-step wizard, as described in [$[DPLAT-004]$]. The **Security Protocol** aspect is primarily addressed in the **Authentication** step (Step 2 of the wizard), which supports two security options:

1. **SAP Cloud Identity Services** – for cloud-based authentication
2. **On-premise certificate-based authentication** – for on-premise SAP landscapes, requiring X.509 certificate upload

Per the [$[Connector Framework — Module Overview]$], the SAP S/4HANA connector uses **OData v4** and **RFC/IDOC** protocols. For security, the connector requires **network-level access** to the SAP landscape, meaning tenant administrators must configure firewall rules and trust relationships before the workspace admin can authenticate.

### SAP S/4 Requirements (Security-Related)

Based on the available sources, the following security requirements apply:

- **Network Access**: Tenant administrators must configure firewall rules and establish trust relationships between the DPLAT platform and the SAP landscape (per [$[Connector Framework — Module Overview]$])
- **Transport Protocol Security**: The connector supports both SOAP and OData v4 transport. SOAP transport requires **WS-Security 1.1 with X.509 certificate authentication** (per [$[DPLAT-REQ-13]$])
- **Certificate Trusts**: Tenant-level settings include certificate trusts for TLS termination (per [$[Connector Framework — Module Overview]$])
- **Credential Management**: Authentication credentials are stored encrypted at rest at the workspace level (per [$[Connector Framework — Module Overview]$])

### How to Validate SAP Connectivity

The validation process is built into the setup wizard:

1. **During Setup**: The wizard includes inline validation at each step before allowing progression (per [$[DPLAT-004]$])
2. **Test Connection**: Upon completing the wizard, a test connection must succeed, and the connector appears in the workspace with status "Configured" (per [$[DPLAT-004]$])
3. **Health Monitoring**: The Connector Health Monitor (F-A3) tracks connection status (healthy, degraded, disconnected) and sync latency for the SAP connector (per [$[Connector Framework — Module Overview]$])
4. **Connection Health Checks**: For both SOAP and OData v4 protocols, connection health checks execute every 5 minutes with a ≤30 second timeout per protocol (per [$[DPLAT-REQ-13]$])

**Note**: The available sources do not provide specific SAP S/4HANA security protocol configuration details (such as specific cipher suites, TLS versions, or certificate formats). The information above is derived from the general connector framework documentation and the SAP-specific requirements and stories.

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-023] SAP — legacy SAP ECC 6.0 compatibility mode](https://demo-jira.local/browse/DPLAT-023)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)

## Data Sync Settings

`⚠ stale`

### How to Set Up SAP S/4HANA

The SAP S/4HANA connector (feature F-A2) is configured through a **4-step guided setup wizard** that guides workspace admins through the process without requiring deep SAP expertise, per [$[DPLAT-004]$]. The wizard steps are:

1. **Connection Details** — Enter the SAP S/4HANA system URL and select the transport protocol (OData v4 or SOAP/RFC)
2. **Authentication** — Configure credentials using either SAP Cloud Identity Services (cloud) or certificate-based authentication (on-premise)
3. **Schema Selection** — Choose which SAP tables, CDS views, or business objects to sync
4. **Review & Connect** — Validate the configuration and establish the connection

Upon completion, the connector appears in the workspace with status "Configured" and a test connection succeeds automatically.

### Data Sync Settings

The Data Sync Settings control how data is extracted from SAP S/4HANA. Key configuration parameters include:

**Sync Mode:**
- **Scheduled (Batch)** — Polling-based extraction on a cron schedule (default for v2.3; real-time CDC is out of scope for this release per [$[DPLAT-EPIC-02]$])
- **Delta queues** — For incremental extraction of changed records only

**Pagination & Streaming:**
- The connector supports **server-side paging** with a configurable `page_size` parameter (default 2000 records, valid range 500–10,000 per [$[DPLAT-012]$])
- For datasets over 100,000 records, progress checkpoints are written to the audit log every 10,000 records, enabling job resumption on failure
- Memory usage stays below 500MB regardless of total record count

**Performance Targets:**
- Minimum throughput of **5,000 records per minute** during full sync (per [$[DPLAT-REQ-04]$])
- End-to-end latency under **200ms per record** (p95) at peak throughput
- Automatic retry on transient failures (max 3 retries with exponential backoff)

**Transport Protocols:**
- **OData v4** — For standard CDS views and business objects; supports batch operations (≥50 requests per batch)
- **SOAP/RFC** — For legacy transactional data and IDOC support; uses WS-Security 1.1 with X.509 certificates

### SAP S/4HANA Requirements

Before configuring the connector, the following prerequisites must be met:

1. **Network Access** — Tenant administrators must configure firewall rules and trust relationships to allow network-level access to the SAP landscape (per [$[Connector Framework — Module Overview]$])
2. **SAP System Version** — SAP S/4HANA (any supported version) or SAP ECC 6.0+ (per [$[Release Notes — v2.4 (Planned)]$])
3. **Authentication** — Either SAP Cloud Identity Services credentials or on-premise X.509 certificates
4. **Transport Protocols** — The SAP system must expose OData v4 endpoints or RFC/SOAP interfaces

### How to Validate SAP Connectivity

The setup wizard includes **inline validation** at each step, with clear error messages before allowing progression to the next step (per [$[DPLAT-004]$]). Specifically:

- **Connection validation** — The wizard performs an OAuth token exchange (for cloud) or certificate handshake (for on-premise) and displays success/failure status
- **Health checks** — Once configured, the Connector Health Monitor (F-A3) tracks connection status (healthy, degraded, disconnected), sync latency, and error rates
- **Test connection** — After completing the wizard, a test connection automatically succeeds, and the connector appears with status "Configured"

**Note:** There is a known bug ([$[DPLAT-DEF-12]$]) where delta syncs may skip records updated within 1 second of the last cursor timestamp. The workaround is to trigger syncs more frequently (every 30 seconds) or run periodic full syncs to reconcile missed records.

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)

## Verification

`⚠ stale`

Based on the available documentation, the SAP S/4 connector setup is part of feature F-A2 within the connector-framework module. Here is the verification-focused guidance:

### SAP S/4 Requirements

Before setting up the SAP S/4 connector, ensure the following prerequisites are met:

1. **SAP System Version**: The connector requires SAP S/4HANA (or SAP ECC 6.0+ for legacy compatibility, per [$[Release Notes — v2.4 (Planned)]$])
2. **Transport Protocols**: The connector supports both SOAP (with WS-Security 1.1 and X.509 certificate authentication) and OData v4 transport protocols (per [$[DPLAT-REQ-13]$])
3. **Network Access**: Outbound IP addresses must be whitelisted in your SAP system's network access settings (based on the Salesforce connector troubleshooting pattern in [$[Salesforce Connector — Troubleshooting Guide]$])
4. **Authentication**: Supports SAP Cloud Identity Services and on-premise certificate-based options (per [$[DPLAT-004]$])

### How to Validate SAP Connectivity

To verify that the SAP S/4 connector is properly configured:

1. **Run the Connection Test**: After completing the 4-step setup wizard (Connection Details → Authentication → Schema Selection → Review & Connect), the connector should appear with status "Configured" and a test connection must succeed (per [$[DPLAT-004]$])

2. **Verify Performance Constraints** (per [$[DPLAT-REQ-04]$]):
   - The connector should sustain **5,000 records per minute** during full sync
   - End-to-end record processing latency should be under **200ms per record (p95)**
   - Automatic retry on transient failures (max 3 retries) should be operational

3. **Check Transport Protocol Health** (per [$[DPLAT-REQ-13]$]):
   - Connection health checks execute every **5 minutes** with ≤30 second timeout per protocol
   - Both SOAP and OData v4 transports should have automatic retry logic (3 attempts, exponential backoff)

4. **Validate Large Dataset Handling** (per [$[DPLAT-012]$]):
   - For queries with more than 10,000 records, server-side paging should activate automatically (default page size: 2,000 records)
   - Memory usage should remain below **500MB** regardless of total record count
   - Progress checkpoints should be written to the audit log every 10,000 records for jobs processing >100,000 records

### Known Issues to Verify

Be aware of these open defects that may affect connectivity validation:

- **Delta sync timing issue** ([$[DPLAT-DEF-12]$]): Records updated within 1 second of the last cursor timestamp may be skipped during delta synchronization. Workaround: trigger sync more frequently (every 30 seconds) or run periodic full syncs
- **Character encoding issue** ([$[DPLAT-DEF-11]$]): German umlauts (ä, ö, ü, ß) in CHAR fields may return null values. Workaround: preprocess source data to replace umlauts with ASCII equivalents

### Verification Checklist

After setup, confirm:
- [ ] Test connection succeeds
- [ ] Connector status shows "Configured"
- [ ] Both SOAP and OData v4 transports respond to health checks
- [ ] Throughput meets 5,000 records/min baseline
- [ ] Large result sets (>10,000 records) use paging without memory issues
- [ ] Audit logs capture connection events and sync progress

**Sources:**
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-DEF-02] Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist](https://demo-jira.local/browse/DPLAT-DEF-02)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)

## Troubleshooting (common)

Based on the available context, the primary documentation for troubleshooting SAP S/4HANA connector issues is the **Salesforce Connector — Troubleshooting Guide** [$[Salesforce Connector — Troubleshooting Guide]$]. However, this guide is specific to the Salesforce connector, not SAP S/4HANA. The SAP S/4HANA connector (feature F-A2) has its own set of known issues and requirements documented in Jira tasks and Confluence pages.

### SAP S/4HANA Requirements

Before setting up the SAP S/4HANA connector, ensure the following requirements are met:

- **Transport Protocols**: The connector supports both SOAP (with WS-Security 1.1 and X.509 certificate authentication) and OData v4 transport protocols (per [$[DPLAT-REQ-13]$]).
- **Performance Baseline**: The connector must sustain a minimum of 5,000 records per minute during full sync operations (per [$[DPLAT-REQ-04]$]).
- **Authentication**: Supports both SAP Cloud Identity Services and on-premise certificate-based options (per [$[DPLAT-004]$]).
- **SAP Version**: For SAP ECC compatibility, target system version 6.0 or later is required (per [$[Release Notes — v2.4 (Planned)]$]).

### Common Troubleshooting Issues

#### 1. German Umlauts Returned as Null in CHAR Fields
- **Symptom**: CHAR fields containing German umlauts (ä, ö, ü, ß) return null values instead of actual characters.
- **Root Cause**: Encoding issue in the connector's character handling for SAP CHAR fields.
- **Workaround**: Manually preprocess source data in SAP to replace umlauts with ASCII equivalents (ae, oe, ue, ss) before extraction, or apply post-processing transformation to restore characters based on known mappings (per [$[DPLAT-DEF-11]$]).
- **Status**: Bug is **Open** and affects approximately 15% of German customer records.

#### 2. Delta Sync Skips Records Updated Within 1 Second of Last Cursor
- **Symptom**: During delta synchronization, records updated within 1 second of the last cursor timestamp are skipped, causing incomplete data sync.
- **Root Cause**: Cursor-based change detection uses `>=` comparison, but sub-second timestamp precision causes some changes to be missed.
- **Workaround**: Manually trigger sync more frequently (every 30 seconds) to reduce the window of potential missed updates, or run a full sync periodically to reconcile skipped records (per [$[DPLAT-DEF-12]$]).
- **Status**: Bug is **In Progress** with **High** priority.

#### 3. Large Result Set Handling
- **Symptom**: Extraction jobs against SAP S/4HANA with large datasets (over 10,000 records) may cause out-of-memory errors or job failures.
- **Root Cause**: Current connector loads all results into memory without streaming.
- **Resolution**: The connector should automatically use server-side paging with configurable page size (default 2,000 records per page) and stream results directly to the output sink. For jobs processing more than 100,000 records, progress checkpoints are written to the audit log every 10,000 records (per [$[DPLAT-012]$]).
- **Status**: Story is **In Progress** for v2.4.

### How to Validate SAP Connectivity

To validate SAP S/4HANA connectivity after setup:

1. **Connection Health Checks**: The connector executes health checks every 5 minutes with a ≤30 second timeout per protocol (per [$[DPLAT-REQ-13]$]).
2. **Test Connection**: After completing the 4-step setup wizard (Connection Details, Authentication, Schema Selection, Review & Connect), a test connection should succeed (per [$[DPLAT-004]$]).
3. **Monitor Error Rates**: The connector error rate should remain below 0.1% for configured data sources (per [$[DPLAT-EPIC-02]$]).

### Escalation

If issues persist, gather the following before contacting support:
- Connector version and tenant ID
- Last successful sync timestamp
- Relevant audit log entries (redact PII)
- SAP system version and transport protocol used

**Note**: The available troubleshooting documentation is primarily for the Salesforce connector. For SAP-specific issues, refer to the Jira tasks [$[DPLAT-DEF-11]$] and [$[DPLAT-DEF-12]$] for known defects and workarounds.

**Sources:**
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📋 [[DPLAT-REQ-04] SAP connector throughput — sustain 5k records/min for full sync](https://demo-jira.local/browse/DPLAT-REQ-04)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-DEF-11] SAP — connector returns null for German umlauts in CHAR fields](https://demo-jira.local/browse/DPLAT-DEF-11)
- 📋 [[DPLAT-DEF-12] SAP — delta sync skips records updated within 1s of last cursor](https://demo-jira.local/browse/DPLAT-DEF-12)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [Salesforce Connector — Troubleshooting Guide](https://demo-confluence.local/wiki/spaces/DPLAT/pages/5925da2c5e5a)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-023] SAP — legacy SAP ECC 6.0 compatibility mode](https://demo-jira.local/browse/DPLAT-023)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
