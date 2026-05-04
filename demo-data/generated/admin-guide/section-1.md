# 1  Introduction

> Overview of administrative responsibilities and system scope.

## System Overview

The Amisol DataPlatform is an enterprise-grade data integration and compliance solution that unifies real-time data movement with policy-enforced retention and privacy controls in a single, multi-tenant SaaS offering. The Admin Guide covers the administrative responsibilities and operational scope for managing this platform.

### Primary Administrative Roles

The system defines two primary administrative roles:

1. **Workspace Admin** — Responsible for provisioning connectors, configuring data pipelines, managing target destinations, and overseeing workspace operations. This role has full access to configure connectors, view PII, and manage retention policies [$[Amisol DataPlatform Demo — Product Overview]$].

2. **Compliance Officer** — Defines retention and tokenization policies, reviews audit logs, and ensures governance requirements are met. This role has audit and governance access but cannot configure connectors [$[Getting Started Guide (Draft)]$].

Additional supporting roles include **Data Engineer** (builds and monitors data flows) and **Analyst** (read-only access to processed data), but the core administrative scope centers on the Workspace Admin and Compliance Officer.

### System Architecture Structure

The platform consists of two integrated modules [$[Amisol DataPlatform Demo — Product Overview]$]:

| Module | Purpose |
|--------|---------|
| **MOD-A Connector Framework** | Real-time data ingestion and change capture from supported data sources |
| **MOD-B Compliance Vault** | Secure archival, PII protection, and automated retention enforcement |

The Connector Framework (MOD-A) comprises six core components: Connector Registry, Config Service, Worker Pool, Secret Vault, Event Bus, and Audit Log [$[Connector Framework — Architecture Deep-Dive]$]. Each tenant receives an isolated logical environment with its own workspaces, connectors, and policies.

### Typical Data Flow

1. Workspace admin configures a **connector** for a supported data source
2. MOD-A ingests changes via **Incremental CDC** and applies **Schema Evolution Handling**
3. Data is delivered to the Compliance Vault
4. MOD-B applies **PII Tokenization** to sensitive fields
5. **Automated Retention Enforcement** manages the lifecycle of archived records
6. All steps are recorded in the **audit log** for compliance review

The Connector Configuration API enables workspace administrators to programmatically provision, update, and manage connector instances, supporting both initial creation and dynamic reconfiguration without service interruption [$[Connector Configuration API — Reference]$]. Authentication requires OAuth 2.0 Bearer Token with the `workspace-admin` role and `connectors:write` scope.

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-022] SAP — BAPI vs OData transport decision matrix](https://demo-jira.local/browse/DPLAT-022)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)

## Scope

The admin guide covers the **Amisol DataPlatform Demo**, an enterprise-grade data integration and compliance solution. Its scope is defined by the platform's two core modules that workspace administrators manage:

1. **MOD-A Connector Framework** — Responsible for real-time data ingestion and change capture from supported data sources (e.g., Salesforce, SAP S/4HANA, PostgreSQL, MySQL, Kafka). Administrators provision, configure, and manage connector instances, including setup wizards, table whitelists, and multi-system aggregation across environments like DEV, QAS, and PRD.

2. **MOD-B Compliance Vault** — Handles secure archival, PII protection, and automated retention enforcement. Administrators oversee PII classification and can review/override automated classifier decisions, while compliance officers define retention and tokenization policies.

### Primary Administrative Roles

The guide addresses three primary user roles, with the **Workspace Admin** as the central figure:

| Role | Responsibilities |
|------|------------------|
| **Workspace Admin** | Provisions connectors, configures pipelines, manages target destinations, reviews PII classifications, and monitors connector health |
| **Data Engineer** | Builds and monitors data flows, handles schema evolution scenarios |
| **Compliance Officer** | Defines retention and tokenization policies, reviews audit logs |

The workspace admin role requires **MFA** before creating the first workspace and holds full access to configure connectors, view PII, and manage retention settings.

### System Architecture Structure

The platform follows a **multi-tenant SaaS architecture** where each tenant receives an isolated logical environment with its own workspaces, connectors, and policies. The architecture consists of:

- **Tenant → Workspace → Connectors** hierarchy, where a workspace is the primary organizational unit containing connectors, data sources, audit logs, and team members
- **Two integrated modules** (MOD-A and MOD-B) that work together in a typical data flow: connector ingests data → MOD-A applies CDC and schema evolution → data delivered to Compliance Vault → MOD-B applies PII tokenization and retention enforcement → all steps recorded in audit log
- **Connector Configuration API** enabling programmatic provisioning and dynamic reconfiguration without service interruption, requiring OAuth 2.0 Bearer Token authentication and the `workspace-admin` role
- **Health Monitor dashboard** providing real-time connector status with color-coded indicators (Green/Yellow/Red) based on sync timestamps, with per-tenant filtering and weekly digest emails for proactive issue identification

The scope of the admin guide therefore encompasses **end-to-end workspace and connector lifecycle management** within the multi-tenant architecture, from initial workspace creation and team member invitations through connector configuration, health monitoring, PII compliance oversight, and audit log management.

**Sources:**
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-022] SAP — BAPI vs OData transport decision matrix](https://demo-jira.local/browse/DPLAT-022)

## Roles

Based on the provided documentation, the scope of the admin guide for the "Roles" subsection focuses on defining the permissions and responsibilities of the primary administrative roles within the Amisol DataPlatform.

The primary administrative role is the **Workspace Admin**. According to the [$[Getting Started Guide (Draft)]$], this role has "Full access to workspace settings," including the ability to configure connectors, view PII, and manage retention policies. The [$[Amisol DataPlatform Demo — Product Overview]$] further specifies that a Workspace Admin "provisions connectors, configures pipelines, manages target destinations." This role is central to the system's operation, as evidenced by multiple Jira tasks (e.g., [$[DPLAT-001]$], [$[DPLAT-007]$], [$[DPLAT-013]$]) which are all scoped for the `workspace-admin` role.

The system architecture is structured around two primary modules, as described in the [$[Amisol DataPlatform Demo — Product Overview]$]:
- **MOD-A Connector Framework**: Handles real-time data ingestion and change capture.
- **MOD-B Compliance Vault**: Manages secure archival, PII protection, and automated retention.

The Workspace Admin operates across both modules, configuring connectors in MOD-A and managing PII tagging and retention in MOD-B. The architecture also supports a **Compliance Officer** role, who "defines and audits retention and privacy policies" and a **Data Engineer** role, who "builds and monitors data flows." The [$[Getting Started Guide (Draft)]$] lists additional roles like **Analyst** and **Viewer**, but the Workspace Admin is the primary administrative role with the broadest set of permissions, including the ability to invite team members and assign these roles.

**Sources:**
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Architecture

The **scope of the admin guide** for the "Architecture" subsection covers the **Connector Framework** and **Compliance Vault** modules of the Amisol DataPlatform, focusing on how workspace administrators provision, configure, and manage data pipelines within a multi-tenant SaaS environment. The guide addresses the system's internal architecture, configuration lifecycle, sync execution model, security model, and observability hooks — all from the perspective of administrative operations.

### Primary Administrative Roles

The system defines two key administrative roles:

- **Workspace Admin** — Provisions connectors, configures pipelines, manages target destinations, and has full access to workspace settings including connector configuration, PII viewing, and retention management (per [$[Getting Started Guide (Draft)]$]).
- **Compliance Officer** — Defines retention and tokenization policies, reviews audit logs, and governs privacy controls (per [$[Amisol DataPlatform Demo — Product Overview]$]).

### System Architecture Structure

The architecture is organized into six primary components within the Connector Framework (per [$[Connector Framework — Architecture Deep-Dive]$]):

| Component | Responsibility |
|-----------|----------------|
| **Connector Registry** | Discovers and manages available connector types |
| **Config Service** | Stores and validates connector configurations |
| **Worker Pool** | Executes sync jobs with lease-based assignment |
| **Secret Vault** | Provides secure access to credentials |
| **Event Bus** | Publishes lifecycle events |
| **Audit Log** | Records all configuration changes |

The configuration lifecycle progresses through four states: **Draft → Validated → Active → Retired**, with all transitions recorded in the audit log. The Worker Pool implements a **lease-based task assignment model** with checkpointing for exactly-once execution, and each tenant has an isolated worker pool with configurable resource limits.

The security model mandates **TLS 1.3 with mutual authentication** for all connector-to-data-source communication, and secrets are stored encrypted at rest using **AES-256-GCM** with per-tenant encryption keys and just-in-time decryption (per [$[Connector Framework — Architecture Deep-Dive]$]).

For the audit log specifically, the v2 architecture (implemented in [$[DPLAT-029]$]) uses **hash-chained entries** for tamper detection and **automatic archival to S3 Glacier** after 90 days, with Postgres as the storage backend (per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$]).

**Sources:**
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Governance

### Scope of the Admin Guide (Governance Aspect)

The admin guide's governance scope covers the **programmatic management and oversight of data integration pipelines** within a multi-tenant SaaS environment. Specifically, it addresses how workspace administrators provision, configure, and monitor connector instances while ensuring compliance with data retention, privacy, and audit requirements. The guide focuses on the **Connector Configuration API** ([$[Connector Configuration API — Reference]$]) and the **Amisol DataPlatform** ([$[Amisol DataPlatform Demo — Product Overview]$]), which together enable controlled data movement from operational systems into analytics and archival workloads.

### Primary Administrative Roles (Governance Context)

The system defines two key governance roles:

1. **Workspace Admin** — Responsible for provisioning connectors, configuring data pipelines, and managing target destinations. This role has full access to connector settings, PII visibility, and retention management ([$[Getting Started Guide (Draft)$]]). The workspace admin is the primary operator for the Connector Configuration API, requiring the `workspace-admin` role and OAuth 2.0 Bearer Token authentication ([$[Connector Configuration API — Reference]$]).

2. **Compliance Officer** — Responsible for defining retention and tokenization policies, reviewing audit logs, and ensuring governance controls are enforced. This role has audit and governance access but cannot configure connectors ([$[Amisol DataPlatform Demo — Product Overview]$]).

### System Architecture Structure (Governance Perspective)

The architecture is structured around two core modules that enforce governance:

- **MOD-A Connector Framework** — Handles real-time data ingestion with incremental CDC and schema evolution. All configuration changes are recorded in the audit log with timestamp, actor, and diff ([$[Connector Framework — Architecture Deep-Dive]$]).

- **MOD-B Compliance Vault** — Applies governance controls including PII tokenization (detecting and replacing sensitive fields like SSN and credit card numbers) and automated retention enforcement (managing lifecycle stages and purging data after retention periods expire) ([$[Amisol DataPlatform Demo — Product Overview]$]).

The audit log system uses a **hash-chained v2 architecture** ([$[DPLAT-029]$]) where each entry includes a cryptographic hash of the previous entry, preventing undetectable tampering. Entries older than 90 days are automatically archived to S3 Glacier, and each entry includes a digital signature verifiable by the compliance officer. This ensures a tamper-evident trail for compliance reviews.

**Key governance controls** include:
- PII handling with masking enabled by default for sensitive fields ([$[Connector Configuration API — Reference]$])
- Retention policies that apply to synced data, with automatic purging after the specified period
- Audit log retention: 90 days for Standard tier, 1 year for Enterprise tier, then archived for 7 years ([$[Customer Success — Internal FAQ]$])
- All connector configuration changes require the `workspace-admin` role and are recorded in the audit log

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Administrative Responsibilities

`⚠ stale`

# Administrative Responsibilities in the Admin Guide

## Scope of the Admin Guide

The admin guide covers the full lifecycle management of a DPLAT workspace, from initial setup through ongoing operational oversight. According to the [$[Getting Started Guide (Draft)]$], the guide addresses workspace creation, team member invitations, role-based access control, and connector configuration. The [$[Connector Configuration API — Reference]$] extends this scope to include programmatic provisioning and dynamic reconfiguration of connector instances without service interruption. Additionally, the [$[Audit Log v1 Architecture (Legacy)]$] establishes the compliance and governance framework, covering immutable event recording, retention policies, and access control for audit data.

## Primary Administrative Roles

The system defines five distinct roles with specific administrative responsibilities, as documented in the [$[Getting Started Guide (Draft)]$]:

| Role | Key Administrative Responsibilities |
|------|-----------------------------------|
| **Workspace Admin** | Full access to workspace settings; can configure connectors, view PII, manage retention, and invite team members |
| **Data Engineer** | Build and maintain data pipelines; can configure connectors and view PII, but cannot manage retention |
| **Analyst** | Read-only access to processed data; can view PII but cannot configure connectors |
| **Viewer** | Limited read access with no PII visibility |
| **Compliance Officer** | Audit and governance access; can view PII and manage retention, but cannot configure connectors |

The **Workspace Admin** role is the primary administrative role, as evidenced by multiple Jira stories targeting this role specifically. For example, [$[DPLAT-001]$] requires workspace admins to validate connector configuration schemas before activation, [$[DPLAT-013]$] empowers them to review and override automated PII classifier decisions, and [$[DPLAT-028]$] sends them weekly digest emails summarizing connector health status.

## System Architecture Structure

The system architecture is organized around three core components that workspace administrators must manage:

1. **Connector Framework (MOD-A)**: This is the data ingestion layer. The [$[Connector Configuration API — Reference]$] describes how workspace admins programmatically provision, update, and manage connector instances. The framework supports multiple connector types (e.g., Salesforce, SAP S/4HANA) and includes a validation layer that checks JSON Schema compliance, retention period ranges (30–2555 days), and duplicate name prevention before activation (per [$[DPLAT-001]$]).

2. **Compliance Vault (MOD-B)**: This handles PII detection and audit logging. The [$[Audit Log v1 Architecture (Legacy)]$] describes an append-only event capture system using a single PostgreSQL table (`audit_events`) that records all data access and modification events. Workspace admins can query audit events and, as noted in [$[DPLAT-029]$], a v2 architecture with hash-chained entries and automatic archival to S3 Glacier is replacing the legacy design.

3. **Health Monitor (F-A3)**: This provides operational visibility. According to [$[DPLAT-007]$], workspace admins see a unified dashboard showing real-time connector status (Green/Yellow/Red) with last sync timestamps and error counts. The dashboard supports per-tenant filtering ([$[DPLAT-026]$]) and sends weekly digest emails ([$[DPLAT-028]$]) to proactively identify integration issues.

**Administrative Responsibility Flow**: Workspace admins configure connectors via the API or setup wizards (e.g., the SAP S/4HANA wizard in [$[DPLAT-004]$]), validate configurations through the framework's validation layer ([$[DPLAT-001]$]), monitor connector health via the dashboard ([$[DPLAT-007]$]), review and override PII classifications ([$[DPLAT-013]$]), and ensure compliance through audit log management ([$[DPLAT-029]$]).

**Sources:**
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [Audit Log v1 Architecture (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/8a5b8693ee64)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)

## Role Definitions

The **scope of the admin guide** focuses on enabling workspace administrators to provision, configure, and manage data integration pipelines within the Amisol DataPlatform. According to the [$[Amisol DataPlatform Demo — Product Overview]$], the platform is an enterprise-grade data integration and compliance solution that unifies real-time data movement with policy-enforced retention and privacy controls in a multi-tenant SaaS offering.

### Primary Administrative Roles

The system defines three primary administrative roles, as documented in the [$[Getting Started Guide (Draft)]$] and [$[Amisol DataPlatform Demo — Product Overview]$]:

| Role | Responsibilities |
|------|------------------|
| **Workspace Admin** | Full access to workspace settings; provisions connectors, configures pipelines, manages target destinations, can view PII, and manage retention policies |
| **Compliance Officer** | Defines retention and tokenization policies, reviews audit logs, has audit and governance access |
| **Data Engineer** | Builds and monitors data flows, handles schema evolution scenarios, can configure connectors and view PII but cannot manage retention |

Additional roles include **Analyst** (read-only access to processed data) and **Viewer** (limited read access, no PII), as per the [$[Getting Started Guide (Draft)]$].

### System Architecture Structure

The platform consists of two core modules that work together, as described in the [$[Amisol DataPlatform Demo — Product Overview]$]:

- **MOD-A Connector Framework**: Handles real-time data ingestion and change capture from supported data sources (e.g., Salesforce, SAP S/4HANA, PostgreSQL, MySQL, Kafka). Key capabilities include Incremental CDC (F-A1) and Schema Evolution Handling (F-A2).
- **MOD-B Compliance Vault**: Applies governance controls including PII Tokenization (F-B1) and Automated Retention Enforcement (F-B2).

Each **tenant** receives an isolated logical environment with its own workspaces, connectors, and policies. The typical data flow involves a workspace admin configuring a connector, MOD-A ingesting changes, data being delivered to the Compliance Vault, MOD-B applying PII protection and retention enforcement, with all steps recorded in the audit log for compliance review.

### Role-Specific Context from Task Trackers

The Jira tasks confirm that the **workspace-admin** role is the primary target for administrative features:
- [$[DPLAT-028]$] implements a weekly digest email for workspace admins summarizing connector health
- [$[DPLAT-029]$] delivers audit log v2 architecture with hash-chained entries for compliance requirements
- [$[DPLAT-024]$] enables multi-system SAP aggregation across DEV/QAS/PRD environments
- [$[DPLAT-021]$] provides table whitelist configuration for SAP connectors
- [$[DPLAT-004]$] offers a guided setup wizard for SAP S/4HANA connector configuration
- [$[DPLAT-026]$] implements per-tenant filtering in the Health Monitor for workspace admins
- [$[DPLAT-007]$] delivers a unified Health Monitor dashboard showing real-time connector status

All these features are explicitly labeled with `role:workspace-admin`, confirming that the admin guide's role definitions center on empowering workspace administrators to manage data pipelines, monitor connector health, and ensure compliance across their assigned tenants.

**Sources:**
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-022] SAP — BAPI vs OData transport decision matrix](https://demo-jira.local/browse/DPLAT-022)

## Access Control

### Scope of the Admin Guide

The admin guide covers the configuration, management, and governance of the Amisol DataPlatform Demo, an enterprise-grade data integration and compliance solution. Specifically for **Access Control**, the guide addresses how workspace administrators provision connectors, manage data pipelines, and enforce security policies across a multi-tenant SaaS environment. The scope includes authentication mechanisms (OAuth 2.0, SAML SSO, email+password), role-based access control (RBAC), multi-factor authentication (MFA) requirements, and audit logging for compliance. According to [$[Amisol DataPlatform Demo — Product Overview]$], the platform unifies real-time data movement with policy-enforced retention and privacy controls, with each tenant receiving an isolated logical environment.

### Primary Administrative Roles

The admin guide defines two primary roles with distinct access control responsibilities:

1. **Workspace Admin** — Has full access to workspace settings, can configure connectors, view PII, manage retention policies, and invite team members. This role is required for API operations like the Connector Configuration API, which mandates the `workspace-admin` role and `connectors:write` scope (per [$[Connector Configuration API — Reference]$]).

2. **Compliance Officer** — Has audit and governance access, can view PII and manage retention policies, but **cannot** configure connectors. This role reviews audit logs and defines tokenization and retention policies (per [$[Amisol DataPlatform Demo — Product Overview]$]).

Additional roles include **Data Engineer** (builds pipelines, can view PII but not manage retention), **Analyst** (read-only access to processed data), and **Viewer** (limited read access, no PII) — as detailed in the [$[Getting Started Guide (Draft)]$].

### System Architecture Structure (Access Control Focus)

The system architecture for access control is structured around two core modules:

| Module | Access Control Aspect |
|--------|----------------------|
| **MOD-A Connector Framework** | Handles authentication to external data sources via OAuth 2.0 bearer tokens, TLS 1.3 with mutual authentication, and secrets management through an encrypted Secret Vault (AES-256-GCM with per-tenant keys). The framework enforces workspace-level isolation and role-based access for connector configuration. |
| **MOD-B Compliance Vault** | Applies PII tokenization and automated retention enforcement. All vault operations are recorded in a tamper-evident audit log with hash-chained entries (per [$[DPLAT-029]$]), ensuring compliance officers can verify data integrity. |

The **Audit Log** is a critical access control component. Per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$], it uses **Postgres** for v2 storage, supporting row-level security per tenant, ACID transactions for audit integrity, and ad-hoc SQL queries for compliance reporting. The audit log records all configuration changes with timestamp, actor, and diff — enabling workspace admins and compliance officers to trace who accessed what data and when.

**Access Control Flow:**
1. Workspace admin authenticates via OAuth 2.0 (or SAML SSO) and must complete MFA before creating workspaces
2. Admin provisions connectors using the Connector Configuration API, which validates the `workspace-admin` role
3. Connector credentials are stored encrypted in the Secret Vault, decrypted just-in-time
4. All data access events are logged to the audit log with hash-chaining for tamper detection
5. Compliance officers review audit logs and enforce retention/tokenization policies

This architecture ensures that access control is enforced at multiple layers: authentication (OAuth/MFA), authorization (RBAC roles), data protection (encryption, PII masking), and auditability (hash-chained logs).

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)

## Compliance Requirements

Based on the provided context, the scope of the admin guide for the "Compliance Requirements" subsection is defined by the **Compliance Vault (MOD-B)** module of the DataPlatform. This module is the privacy and governance layer that enables tenants to identify, classify, and track access to sensitive data to ensure alignment with regulatory requirements such as **GDPR** and the German **BDSG**.

The primary administrative roles involved in compliance are:
- **Compliance Officer**: Responsible for viewing and exporting audit logs, configuring PII rules, and approving overrides. This role is typically assigned to the Legal/Privacy team. Per [$[DPLAT-REQ-10]$], only this role can trigger audit log exports.
- **Workspace Admin**: Manages PII tagging for their workspace, including reviewing and overriding automated classifier decisions. This role is typically assigned to a data team lead. Per [$[DPLAT-013]$], workspace admins can override classifications, but all such actions are logged.
- **Data Steward**: Reviews PII classifications and requests corrections. This role is typically assigned to a subject matter expert.

The system architecture is structured to enforce compliance at the point of data ingestion. The **PII Auto-Tagging (F-B1)** feature operates synchronously during the ingestion pipeline: a connector extracts raw data, the PII detection engine (a hybrid of rule-based and ML models) classifies it, and the data is tagged with metadata before being stored. This at-ingestion approach prevents untagged sensitive data from entering downstream analytics. The **Audit Log Export (F-B2)** feature provides immutable records of all data access and modification events, with a v2 architecture that uses hash-chained entries for tamper detection and automatic archival to S3 Glacier after 90 days, as detailed in [$[DPLAT-029]$].

From a compliance requirements perspective, the architecture enforces strict **data residency** controls. Per [$[DPLAT-REQ-07]$] and [$[DPLAT-REQ-16]$], PII classifier inference must run exclusively within the tenant's designated geographic region, with zero cross-border data transfers allowed to comply with GDPR Art. 44 and BDSG. Additionally, a **retention contract** applies: PII-tagged data has a platform-wide default retention period of **30 days**, after which it is automatically anonymized or deleted. Per-tenant overrides are possible but require a compliance review via [$[DPLAT-006]$]. All retention policy changes are logged in the immutable audit trail.

**Sources:**
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-REQ-16] PII — model inference must run within tenant geo-region](https://demo-jira.local/browse/DPLAT-REQ-16)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)

## Audit Scope

The **admin guide** covers the configuration, management, and governance of the Amisol DataPlatform, focusing on two primary modules: the **Connector Framework (MOD-A)** for data ingestion and the **Compliance Vault (MOD-B)** for secure archival and retention enforcement. The scope is specifically oriented toward the administrative tasks required to set up, monitor, and audit data pipelines within a multi-tenant SaaS environment.

### Primary Administrative Roles

The guide identifies three key administrative roles, each with distinct responsibilities within the audit scope:

- **Workspace Admin**: Provisions connectors, configures data pipelines, manages target destinations, and has full access to workspace settings. This role is responsible for initiating and overseeing all data movement activities that generate audit log entries.
- **Compliance Officer**: Defines retention and tokenization policies, reviews audit logs, and manages governance controls. This role is the primary consumer of audit data for compliance reviews and reporting.
- **Data Engineer**: Builds and monitors data flows, handles schema evolution scenarios, and ensures pipeline reliability. While not directly managing policies, this role's activities are recorded in the audit log.

### System Architecture Structure

The system architecture is structured around two integrated modules that work together to support the audit scope:

1. **MOD-A Connector Framework**: Handles real-time data ingestion and change capture from supported data sources. It includes components such as the Connector Registry, Config Service, Worker Pool, Secret Vault, Event Bus, and Audit Log. Each connector emits an audit log entry for every batch processed, ensuring traceability from source to target.

2. **MOD-B Compliance Vault**: Receives data from MOD-A pipelines and applies governance controls. Key capabilities include PII Tokenization (F-B1) and Automated Retention Enforcement (F-B2). All vault operations are recorded in the audit log, providing a tamper-evident trail for compliance reviews.

The audit log itself is a critical architectural component, storing all data access and modification events across connectors. Per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)$]$], the system uses **Postgres** for v2 audit log storage, supporting up to 500K events/hour with 12-month hot retention and multi-tenant row-level security. The audit log supports both operational debugging (recent events) and compliance reporting (historical aggregations) through a domain-specific query language documented in the [$[Audit Log — Query Language Reference]$].

### Audit Scope Summary

The audit scope encompasses:
- **All connector configuration changes** (creation, updates, state transitions from Draft to Retired)
- **All data access and modification events** across connectors, including actor identity, resource path, timestamp, and data volume
- **Compliance Vault operations** including PII tokenization and retention enforcement actions
- **Audit log export jobs** monitored via the Health Monitor dashboard (per [$[DPLAT-043]$])
- **Hash-chained entries** with digital signatures for tamper detection, with automatic archival to S3 Glacier after 90 days (per [$[DPLAT-029]$])

The guide does not cover customer billing, support escalation procedures, or legal NDA processes, which are documented separately in the Customer Success FAQ.

**Sources:**
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)

## Security Framework

The **scope of the admin guide** within the Security Framework covers the configuration, management, and governance of data connectors in the Amisol DataPlatform, specifically focusing on secure data ingestion, authentication, secrets management, and compliance controls. The guide addresses how workspace administrators provision and manage connector instances while maintaining strict security boundaries across multi-tenant deployments.

### Primary Administrative Roles

The Security Framework defines three primary administrative roles with distinct security responsibilities:

1. **Workspace Admin** — Configures connectors, manages authentication credentials, sets PII handling rules, and controls sync schedules. This role requires the `workspace-admin` role and `connectors:write` scope for API access, as documented in the [$[Connector Configuration API — Reference]$].

2. **Compliance Officer** — Has read-only access to audit logs and PII mappings. This role reviews who modified connector configurations and ensures retention policies align with regulatory requirements (e.g., GDPR, CCPA).

3. **Tenant Admin** — Manages network-level security configurations, including firewall rules, certificate trusts for TLS termination, and global rate-limit defaults. This role is responsible for establishing the secure foundation before workspace admins can authenticate.

### System Architecture Structure (Security-Focused)

The system architecture is structured with security embedded at every layer:

**Authentication & Authorization Layer:**
- All API access requires OAuth 2.0 Bearer Tokens with the `workspace-admin` role and `connectors:write` scope
- The [$[Connector Configuration API — Reference]$] enforces role-based access control, returning HTTP 403 for unauthorized users

**Secrets Management:**
- Connector credentials are never stored in plaintext
- The Secret Vault provides AES-256-GCM encryption at rest with per-tenant encryption keys
- Just-in-time decryption with automatic revocation ensures credentials are only accessible when needed

**Communication Security:**
- All connector-to-data-source communication uses TLS 1.3 with mutual authentication
- Certificate pinning is required for production connectors
- Certificate rotation includes a 30-day warning window, per DPLAT-REQ-11

**Data Protection:**
- PII handling includes field-level masking (e.g., SSN, credit_card fields)
- Retention periods are validated between 30 and 2555 days (approximately 7 years), as confirmed by the compliance officer in [$[DPLAT-001]$]
- All configuration changes are recorded in the audit log with timestamp, actor, and change diff

**Multi-Tenant Isolation:**
- Each tenant has an isolated worker pool with configurable resource limits
- Tenant-level settings (network policies, certificate trusts) are managed separately from workspace-level settings (authentication credentials, sync schedules)

The Security Framework ensures that workspace admins can securely provision and manage connectors while compliance officers maintain oversight through audit trails and PII controls, all within a strictly isolated multi-tenant architecture.

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-022] SAP — BAPI vs OData transport decision matrix](https://demo-jira.local/browse/DPLAT-022)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)

## Encryption Standards

### Scope of the Admin Guide

The admin guide covers the configuration and management of the Amisol DataPlatform, an enterprise-grade data integration and compliance solution. Its scope includes provisioning connectors, managing data pipelines, defining retention and privacy policies, and overseeing audit and compliance operations. The guide is primarily aimed at **workspace admins** and **compliance officers**, who are responsible for configuring integrations and enforcing governance controls within their tenant.

### Primary Administrative Roles

The two primary administrative roles relevant to encryption standards are:

- **Workspace Admin** — Provisions connectors, configures pipelines, and manages target destinations. This role is responsible for setting up encryption-related configurations such as PII handling (e.g., enabling `pii_handling.masking_enabled` in connector settings) and managing tenant encryption keys via the Key Management API (per [$[DPLAT-REQ-19]$]).
- **Compliance Officer** — Defines retention and tokenization policies, reviews audit logs, and verifies encryption status. This role can confirm that audit log data is encrypted at rest using AES-256-GCM with tenant-managed keys (BYOK) and can inspect key metadata without accessing encrypted content (per [$[DPLAT-REQ-19]$]).

### System Architecture Structure (Encryption Focus)

The system architecture is structured around two core modules:

1. **MOD-A Connector Framework** — Handles real-time data ingestion. All connector-to-data-source communication uses **TLS 1.3 with mutual authentication** and certificate pinning for production connectors (per [$[Connector Framework — Architecture Deep-Dive]$]). Connector credentials are never stored in plaintext; they are encrypted at rest using **AES-256-GCM** in the Secret Vault, with per-tenant encryption keys and just-in-time decryption.

2. **MOD-B Compliance Vault** — Applies governance controls. This module enforces **encryption-at-rest for audit logs** using **AES-256-GCM** with **Bring-Your-Own-Key (BYOK)** support, where tenant-managed keys are stored in AWS KMS or Azure Key Vault (per [$[DPLAT-REQ-19]$]). The audit log v2 architecture (per [$[DPLAT-029]$]) implements hash-chained entries for tamper detection, with automatic archival to S3 Glacier after 90 days. Additionally, cached Salesforce connector data is encrypted at rest using AES-256 and never exposed outside the tenant boundary (per [$[Salesforce Connector — Business Rules]$]).

In summary, encryption is embedded at multiple layers: transport (TLS 1.3), credential storage (AES-256-GCM in Secret Vault), cached data (AES-256), and audit logs (AES-256-GCM with BYOK), ensuring end-to-end protection aligned with enterprise security requirements.

**Sources:**
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-016] Salesforce — field-mapping UI for custom object aliases](https://demo-jira.local/browse/DPLAT-016)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)

## Identity Management

### Scope of the Admin Guide

The admin guide for the Amisol DataPlatform covers the complete lifecycle of workspace and tenant administration, with a specific focus on **Identity Management** as the foundational layer for secure platform access. According to the [$[Getting Started Guide (Draft)]$], the guide walks administrators through initial setup, authentication configuration, user provisioning, and role-based access control. The Identity Management aspect specifically addresses how users are onboarded, authenticated, and authorized within the multi-tenant DPLAT environment.

### Primary Administrative Roles

The system defines two key administrative roles relevant to Identity Management:

1. **Tenant Administrator** — The top-level administrator who creates user accounts and sends invitation emails. Per the [$[Getting Started Guide (Draft)]$], this role is responsible for provisioning new DPLAT accounts and managing the initial authentication setup.

2. **Workspace Admin** — The primary operational administrator who manages workspace-level access. According to the [$[Amisol DataPlatform Demo — Product Overview]$], workspace admins provision connectors, configure pipelines, and manage team members within their workspace. They have full access to workspace settings, can configure connectors, view PII, and manage retention policies.

Additional roles that interact with identity management include **Data Engineers** (build and maintain pipelines), **Analysts** (read-only access to processed data), **Viewers** (limited read access, no PII), and **Compliance Officers** (audit and governance access).

### System Architecture Structure for Identity Management

The Identity Management architecture follows a **multi-tenant, role-based access control (RBAC)** model:

- **Tenant Isolation**: Each tenant receives an isolated logical environment with its own workspaces, connectors, and policies. This is confirmed by both the [$[Amisol DataPlatform Demo — Product Overview]$] and the [$[Getting Started Guide (Draft)]$].

- **Authentication Methods**: The system supports three authentication options — Email + Password (direct registration), SAML SSO (via organization's identity provider), and OAuth (Google, Microsoft, or other providers). This is documented in the [$[Getting Started Guide (Draft)]$].

- **Multi-Factor Authentication (MFA)**: MFA is required for workspace administrators before they can create their first workspace, though regular users can configure it later in Account Settings.

- **Role-Based Access Control**: The system uses a hierarchical role model where workspace admins have full access, while other roles have progressively restricted permissions. The [$[Connector Configuration API — Reference]$] confirms that API access requires the `workspace-admin` role and OAuth 2.0 Bearer Token authentication.

- **Audit Trail**: All identity-related actions (user invitations, role changes, authentication events) are recorded in the audit log, which uses a hash-chained architecture for tamper detection (per [$[DPLAT-029]$]).

In summary, the Identity Management aspect of the admin guide covers user provisioning, authentication configuration, role assignment, and access control within a secure, multi-tenant architecture where workspace admins serve as the primary operational administrators.

**Sources:**
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)

## Data Privacy

The admin guide for the **Amisol DataPlatform** covers the configuration and management of the **Compliance Vault (MOD-B)**, which serves as the privacy and governance layer of the platform. From a **Data Privacy** perspective, the guide's scope includes:

1. **Enabling and configuring PII Auto-Tagging (F-B1)** — automated detection and classification of personally identifiable information across ingested datasets
2. **Setting up Audit Log Export (F-B2)** — immutable, hash-chained records of all data access and modification events
3. **Defining retention policies** for audit logs and archived data
4. **Configuring PII handling at the connector level** — including masking and field exclusion (per the [$[Connector Configuration API — Reference]$])

## Primary Administrative Roles

The guide defines three specialized roles with distinct data privacy responsibilities:

| Role | Data Privacy Responsibilities |
|------|------------------------------|
| **Compliance Officer** | View and export audit logs, configure PII detection rules, verify digital signatures on audit entries |
| **Workspace Admin** | Manage PII tagging for their workspace, configure connector-level PII handling (masking, excluded fields) |
| **Data Steward** | Review PII classifications, request corrections to misclassified sensitive data |

Per the [$[Amisol DataPlatform Demo — Product Overview]$], the **Workspace Admin** provisions connectors and manages data pipelines, while the **Compliance Officer** defines and audits retention and privacy policies.

## System Architecture — Data Privacy Aspect

The architecture relevant to data privacy consists of two integrated modules:

1. **MOD-A (Connector Framework)** — Ingests data from sources via Incremental CDC (F-A1). At this stage, PII handling is configured per connector, including masking and field exclusion (as shown in the Connector Configuration API with `pii_handling.masking_enabled` and `excluded_fields`).

2. **MOD-B (Compliance Vault)** — Applies governance controls:
   - **PII Auto-Tagging (F-B1)** — Scans column values using regex patterns and ML classifiers, tagging fields with standardized categories (Email, Phone, National ID, Name, Address, IP Address)
   - **Audit Log Export (F-B2)** — Records all data access, modification, permission changes, and authentication events in a hash-chained, tamper-evident log stored in **Postgres** (per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$]), with automatic archival to S3 Glacier after 90 days (per [$[DPLAT-029]$])

The data flow for privacy-sensitive data is:
1. Connector ingests data → 2. PII Auto-Tagging classifies sensitive fields → 3. PII Tokenization replaces sensitive values with deterministic tokens → 4. All operations recorded in audit log → 5. Retention policies manage lifecycle and deletion

This architecture ensures alignment with **GDPR** and **German BDSG** requirements, including lawful processing, data minimization, data subject rights, and accountability through immutable audit trails.

**Sources:**
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-022] SAP — BAPI vs OData transport decision matrix](https://demo-jira.local/browse/DPLAT-022)

## Audit Logging

The admin guide for the **Audit Logging** aspect of the MOD-B Compliance Vault module covers the configuration, management, and querying of compliance-critical audit events across the Amisol DataPlatform. Its scope includes:

- **Configuration**: Setting up the audit-log-service via environment variables such as `AUDIT_LOG_ENABLED`, `AUDIT_RETENTION_DAYS` (default 2555 days), `AUDIT_STORAGE_BACKEND` (Postgres or ClickHouse), and `AUDIT_COMPRESSION_ENABLED` (per [$[audit-log-service — README]$]).
- **Storage Architecture**: The v2 architecture uses Postgres with hash-chained entries for tamper detection and automatic archival to S3 Glacier after 90 days (per [$[DPLAT-029]$] and [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)$]$]).
- **Querying**: A domain-specific query language (DSL) for filtering by event type, timestamp, actor, resource path, and metadata, with aggregation capabilities (per [$[Audit Log — Query Language Reference]$]).
- **Compliance Features**: Encryption-at-rest with tenant-managed keys (BYOK) using AES-256-GCM, schema versioning with backward compatibility for 2 years, and PII redaction (per [$[DPLAT-REQ-19]$] and [$[DPLAT-REQ-20]$]).
- **Monitoring**: Integration with the Connector Health Monitor dashboard to display Audit Log Export job status (per [$[DPLAT-043]$]).

## Primary Administrative Roles

The primary administrative roles relevant to audit logging are:

- **Workspace Admin**: Full access to workspace settings, including configuring audit log retention, managing encryption keys, and viewing audit logs. They can also preview schema changes in a staging tenant before production deployment (per [$[Getting Started Guide (Draft)]$] and [$[DPLAT-REQ-20]$]).
- **Compliance Officer**: Audit and governance access, including verifying encryption status and key metadata via the Audit Log Export feature, without accessing encrypted content (per [$[Getting Started Guide (Draft)]$] and [$[DPLAT-REQ-19]$]).
- **Data Engineer**: Can configure connectors and view PII but cannot manage retention policies (per [$[Getting Started Guide (Draft)]$]).

## System Architecture Structure (Audit Logging Focus)

The system architecture for audit logging is structured as follows:

- **Core Component**: The **audit-log-service** is a core component of the MOD-B Compliance Vault module, implementing feature F-B2 (Audit Log Storage and Retrieval). It provides centralized logging for all compliance-critical events, including data access, modifications, and administrative actions (per [$[audit-log-service — README]$]).
- **Integration**: The service integrates with the **Connector Framework** via the Event Bus, which publishes lifecycle events that are recorded in the audit log. The Connector Framework's Audit Log component records all configuration changes (per [$[Connector Framework — Architecture Deep-Dive]$]).
- **Storage Backend**: The v2 architecture uses **Postgres** for storage, chosen for its operational simplicity, query flexibility (full SQL), transaction integrity (ACID), and multi-tenant isolation via row-level security. ClickHouse is reserved for potential v3 evaluation if performance or cost thresholds are exceeded (per [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)$]$]).
- **Data Flow**: Audit events are ingested at high volume, stored with hash-chained entries for tamper detection, and automatically archived to S3 Glacier after 90 days. Queries are submitted via the `/api/v1/compliance/audit-query` endpoint or through the Compliance Vault UI (per [$[Audit Log — Query Language Reference]$] and [$[DPLAT-029]$]).
- **Security**: Encryption-at-rest uses AES-256-GCM with tenant-managed keys (BYOK) stored in AWS KMS or Azure Key Vault, with automatic key rotation every 90 days (per [$[DPLAT-REQ-19]$]).
- **Monitoring**: The Audit Log Export job status is displayed in the Connector Health Monitor dashboard, refreshing every 30 seconds with color-coded status indicators (per [$[DPLAT-043]$]).

**Sources:**
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [audit-log-service — README](https://demo-bitbucket.local/audit-log-service/blob/main/README.md)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Audit Log — Query Language Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/58e054f47468)
- 📋 [[DPLAT-043] Health Monitor — include Audit Log Export job status panel](https://demo-jira.local/browse/DPLAT-043)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-REQ-19] Audit Log — encryption-at-rest with tenant-managed keys (BYOK)](https://demo-jira.local/browse/DPLAT-REQ-19)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-REQ-10] Audit Log Export — RBAC: only Compliance Officer role can trigger export](https://demo-jira.local/browse/DPLAT-REQ-10)
- 📋 [[DPLAT-010] Audit Log Export — compliance officer can trigger ad-hoc export with date range](https://demo-jira.local/browse/DPLAT-010)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)

## Glossary

Based on the provided documentation, the **scope of the admin guide** covers the configuration, provisioning, and management of data connectors and compliance policies within the Amisol DataPlatform (DPLAT). It focuses on enabling workspace administrators to set up data pipelines, manage retention, and oversee governance controls.

### Primary Administrative Roles

The system defines several key administrative roles, as detailed in the [$[Amisol DataPlatform Demo — Product Overview]$] and [$[Getting Started Guide (Draft)]$]:

- **Workspace Admin**: Has full access to workspace settings, can provision connectors, configure data pipelines, manage target destinations, and control retention policies.
- **Compliance Officer**: Defines and audits retention and tokenization policies, reviews audit logs, and has governance access.
- **Data Engineer**: Builds and monitors data flows, handles schema evolution scenarios, and can configure connectors but cannot manage retention.

### System Architecture Structure

The platform architecture, as described in the [$[Amisol DataPlatform Demo — Product Overview]$], consists of two primary modules:

| Module | Purpose |
|--------|---------|
| **MOD-A Connector Framework** | Real-time data ingestion and change capture from supported data sources (e.g., PostgreSQL, MySQL, Kafka, SAP S/4HANA) |
| **MOD-B Compliance Vault** | Secure archival, PII protection (tokenization), and automated retention enforcement |

Each **tenant** receives an isolated logical environment with its own workspaces, connectors, and policies. The Connector Framework itself, per the [$[Connector Framework — Architecture Deep-Dive]$], comprises six internal components: Connector Registry, Config Service, Worker Pool, Secret Vault, Event Bus, and Audit Log. Connector configurations progress through four lifecycle states: Draft → Validated → Active → Retired.

### Glossary Context

For the **Glossary** subsection, the key terms to define are:
- **Workspace**: The primary organizational unit containing connectors, data sources, audit logs, and team members.
- **Connector**: A configured instance that pulls data from a specific data source (e.g., Salesforce, SAP S/4HANA).
- **Audit Log**: A tamper-evident record of all configuration changes and data operations, now using a hash-chained v2 architecture (per [$[DPLAT-029]$]).
- **PII Tokenization**: The process of replacing sensitive fields (e.g., email, SSN) with deterministic tokens while preserving referential integrity.

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Terminology

The **scope of the admin guide** for the Amisol DataPlatform covers the configuration, management, and monitoring of data integration pipelines within a multi-tenant SaaS environment. Specifically, the guide addresses how workspace administrators provision connectors, manage data sources, configure retention and privacy policies, and oversee the health of data flows across the platform's two core modules: **MOD-A Connector Framework** (real-time data ingestion) and **MOD-B Compliance Vault** (secure archival and governance) [$[Amisol DataPlatform Demo — Product Overview]$].

### Primary Administrative Roles

The admin guide defines three primary user roles, each with distinct responsibilities [$[Amisol DataPlatform Demo — Product Overview]$]:

| Role | Responsibilities |
|------|------------------|
| **Workspace Admin** | Provisions connectors, configures pipelines, manages target destinations, and has full access to workspace settings |
| **Data Engineer** | Builds and monitors data flows, handles schema evolution scenarios |
| **Compliance Officer** | Defines retention and tokenization policies, reviews audit logs |

The **workspace admin** is the central role for the admin guide, as they are responsible for connector lifecycle management, team member invitations, and workspace configuration [$[Getting Started Guide (Draft)]$].

### System Architecture Structure

The platform architecture consists of two integrated modules [$[Amisol DataPlatform Demo — Product Overview]$]:

1. **MOD-A Connector Framework** — Handles real-time data ingestion and change capture from supported data sources (e.g., PostgreSQL, MySQL, SAP S/4HANA, Kafka) using incremental CDC and schema evolution handling
2. **MOD-B Compliance Vault** — Applies governance controls including PII tokenization and automated retention enforcement

Each **tenant** receives an isolated logical environment with its own workspaces, connectors, and policies. A **workspace** serves as the primary organizational unit containing connectors, data sources, audit logs, and team members [$[Getting Started Guide (Draft)]$]. The audit log system uses a **Postgres** backend with hash-chained entries for tamper detection and automatic archival to S3 Glacier after 90 days [$[ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)]$][$[DPLAT-029] Audit Log v2 architecture$].

### Key Terminology

- **Connector**: A configured instance that ingests data from a specific data source type (e.g., SAP S/4HANA, Salesforce) [$[Connector Configuration API — Reference]$]
- **Data Source**: The operational system from which data is extracted (e.g., SAP DEV/QAS/PRD environments) [$[DPLAT-024] SAP — multi-system aggregation$]
- **Audit Log**: A tamper-evident record of all data access and modification events, used for compliance verification [$[ADR-007]$]
- **Health Monitor**: A dashboard providing real-time status of all configured connectors, with per-tenant filtering and weekly digest emails to workspace admins [$[DPLAT-026] Health Monitor — per-tenant filter$][$[DPLAT-028] Health Monitor — weekly digest$]

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-022] SAP — BAPI vs OData transport decision matrix](https://demo-jira.local/browse/DPLAT-022)

## Acronyms

Based on the provided context, the scope of the admin guide, specifically for the "Acronyms" subsection of the "Introduction," is defined by the system's architecture and the primary administrative roles.

**Primary Question: What is the scope of the admin guide?**

The scope of the admin guide, as it relates to acronyms, covers the two core modules of the Amisol DataPlatform Demo: **MOD-A Connector Framework** and **MOD-B Compliance Vault** (per [$[Amisol DataPlatform Demo — Product Overview]$]). The guide explains the acronyms for these modules and their key capabilities, such as **CDC** (Change Data Capture) for MOD-A and **PII** (Personally Identifiable Information) tokenization for MOD-B. It also defines acronyms for the system's components, such as the **API** (Application Programming Interface) used for connector configuration (per [$[Connector Configuration API — Reference]$]).

**Related: Who are the primary administrative roles?**

The primary administrative roles, which are key acronyms in the guide, are:
- **Workspace Admin**: The role responsible for provisioning connectors, configuring pipelines, and managing data sources (per [$[Amisol DataPlatform Demo — Product Overview]$] and [$[Getting Started Guide (Draft)]$]).
- **Compliance Officer**: The role that defines retention and tokenization policies and reviews audit logs (per [$[Amisol DataPlatform Demo — Product Overview]$]).
- **Data Engineer**: The role that builds and monitors data flows (per [$[Amisol DataPlatform Demo — Product Overview]$]).

**Related: How is the system architecture structured?**

The system architecture is structured around two main modules, which are the primary acronyms:
- **MOD-A (Connector Framework)**: Handles real-time data ingestion and change capture. Its internal components include the **Connector Registry**, **Config Service**, **Worker Pool**, **Secret Vault**, **Event Bus**, and **Audit Log** (per [$[Connector Framework — Architecture Deep-Dive]$]).
- **MOD-B (Compliance Vault)**: Manages secure archival, PII protection, and automated retention enforcement (per [$[Amisol DataPlatform Demo — Product Overview]$]).

The architecture also defines a **tenant** as an isolated logical environment with its own workspaces, connectors, and policies (per [$[Amisol DataPlatform Demo — Product Overview]$]).

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Reference Links

Based on the provided context, the scope of the admin guide for the "Reference Links" subsection is to provide workspace administrators with the authoritative, technical documentation and links necessary to configure, manage, and troubleshoot the platform's core components. The primary reference links point to the **Connector Configuration API** and the **Connector Framework Architecture**.

**Primary Question: What is the scope of the admin guide?**

The scope of the admin guide, as defined by the reference links, is to cover the programmatic management of the platform. This includes provisioning, updating, and managing connector instances via the [$[Connector Configuration API — Reference]$], and understanding the internal architecture of the core integration subsystem as detailed in the [$[Connector Framework — Architecture Deep-Dive]$]. The guide focuses on the technical operations required to set up and maintain data pipelines.

**Related: Who are the primary administrative roles?**

The primary administrative roles are:
- **Workspace Admin:** Responsible for provisioning connectors, configuring pipelines, and managing target destinations (per [$[Amisol DataPlatform Demo — Product Overview]$]).
- **Compliance Officer:** Defines retention and tokenization policies and reviews audit logs (per [$[Amisol DataPlatform Demo — Product Overview]$]).
- **Data Engineer:** Builds and monitors data flows and handles schema evolution scenarios (per [$[Amisol DataPlatform Demo — Product Overview]$]).

**Related: How is the system architecture structured?**

The system architecture is structured around two primary modules (per [$[Amisol DataPlatform Demo — Product Overview]$]):
1.  **MOD-A Connector Framework:** Handles real-time data ingestion and change capture.
2.  **MOD-B Compliance Vault:** Manages secure archival, PII protection, and automated retention enforcement.

The Connector Framework itself is composed of six components (per [$[Connector Framework — Architecture Deep-Dive]$]): Connector Registry, Config Service, Worker Pool, Secret Vault, Event Bus, and Audit Log.

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)

## Version History

`⚠ stale`

Based on the available documentation, the **scope of the admin guide** for the Amisol DataPlatform centers on enabling **workspace administrators** to provision, configure, and manage data integration pipelines within a multi-tenant SaaS environment. The guide covers two primary modules: the **MOD-A Connector Framework** (for real-time data ingestion and change capture) and the **MOD-B Compliance Vault** (for secure archival, PII protection, and retention enforcement). Key administrative activities include creating and managing connectors, configuring sync schedules, setting retention policies, and monitoring connector health.

**Primary administrative roles** are:
- **Workspace Admin** — Full access to configure connectors, manage pipelines, view PII, and set retention policies
- **Data Engineer** — Builds and monitors data flows, handles schema evolution
- **Compliance Officer** — Defines retention and tokenization policies, reviews audit logs

**System architecture** is structured as two integrated modules: MOD-A handles ingestion via incremental CDC and schema evolution, while MOD-B applies governance controls. Each tenant gets an isolated logical environment with its own workspaces, connectors, and policies.

### Version History Relevance

The **Version History** aspect of the admin guide is directly informed by several completed Jira tasks and architectural decisions:

- **[$[DPLAT-029]$]** — The audit log system was upgraded from a legacy v1 single-table design to a **v2 architecture** with hash-chained entries and automatic archival to S3 Glacier after 90 days. This change, implemented in **v2.3**, replaced the previous approach and required migration of existing data. The admin guide should document that v2 audit logs include cryptographic signatures for tamper detection and that compliance officers can verify log integrity.

- **[$[DPLAT-REQ-20]$]** — The audit log schema now supports **versioning with backward compatibility for at least 2 prior schema versions**, ensuring historical queries remain functional. Schema migrations must complete within 15 minutes per tenant during off-peak windows. The admin guide should note that workspace admins can preview schema changes in a staging tenant before applying to production.

- **[$[ADR-007]$]** — The storage backend for audit logs was decided as **Postgres for v2**, with ClickHouse reserved for potential v3 evaluation if performance thresholds are exceeded. This decision was driven by operational simplicity, ACID transaction integrity, and native multi-tenant row-level security. The admin guide should reflect that Postgres is the current backend, with a migration path to ClickHouse documented if needed.

- **[$[DPLAT-026]$]** and **[$[DPLAT-007]$]** — The **Health Monitor dashboard** (feature F-A3) was implemented in **v2.3**, providing workspace admins with a unified view of connector status (Green/Yellow/Red), last sync timestamps, and error counts. Per-tenant filtering was added in [$[DPLAT-026]$] to scope the view to the admin's assigned workspace. The admin guide should document that status colors are calculated based on sync recency (1h/6h thresholds) and that filtering persists across sessions.

- **[$[DPLAT-028]$]** — A **weekly digest email** for workspace admins is in progress for **v2.4**, summarizing connector health and suppressed when all connectors are healthy.

- **[$[DPLAT-004]$]** and **[$[DPLAT-021]$]** — The **SAP S/4HANA connector** setup wizard (4-step: Connection Details, Authentication, Schema Selection, Review & Connect) and **table whitelist configuration** were delivered in **v2.3**, allowing admins to control which tables are synced and ensure PII compliance.

- **[$[DPLAT-024]$]** — Multi-system SAP aggregation across DEV/QAS/PRD environments is planned for **v2.5**, enabling workspace admins to manage up to 3 SAP instances per workspace with independent credentials.

In summary, the **Version History** section of the admin guide should document that **v2.3** introduced the core audit log v2 architecture, Health Monitor dashboard, SAP connector wizard and whitelist, and schema versioning. **v2.4** will add the weekly digest email. **v2.5** will bring multi-system SAP aggregation. The guide should also note that the audit log backend is Postgres (per ADR-007) with a potential future migration to ClickHouse if performance requirements demand it.

**Sources:**
- 📋 [[DPLAT-026] Health Monitor — per-tenant filter and view scoping](https://demo-jira.local/browse/DPLAT-026)
- 📋 [[DPLAT-029] Audit Log v2 architecture — replaces v1 single-table design (legacy)](https://demo-jira.local/browse/DPLAT-029)
- 📋 [[DPLAT-024] SAP — multi-system aggregation across DEV/QAS/PRD](https://demo-jira.local/browse/DPLAT-024)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-028] Health Monitor — weekly digest email to admin role](https://demo-jira.local/browse/DPLAT-028)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-REQ-20] Audit Log — schema versioning with backward compatibility for 2y](https://demo-jira.local/browse/DPLAT-REQ-20)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Getting Started Guide (Draft)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b02ddc19a0)
- 📄 [ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/59ab00079e90)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
