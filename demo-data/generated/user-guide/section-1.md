# 1  Introduction

> Overview of the platform capabilities

## Welcome Overview

The **Amisol DataPlatform Demo** is an enterprise-grade data integration and compliance solution designed to help organizations move data from operational systems into analytics and archival workloads while maintaining strict governance. The platform unifies real-time data movement with policy-enforced retention and privacy controls in a single, multi-tenant SaaS offering.

### Who Can Use the Connectors?

The connectors are primarily used by **workspace administrators**, who provision connectors, configure data pipelines, and manage target destinations. Additionally, **data engineers** build and monitor data flows, while **compliance officers** define retention and tokenization policies and review audit logs. Each tenant gets an isolated logical environment with its own set of workspaces, connectors, and policies.

### Core Features

The platform consists of two integrated modules:

- **MOD-A Connector Framework** — Provides real-time data ingestion and change capture from supported data sources (including Salesforce, SAP S/4HANA, PostgreSQL, MySQL, and Kafka). Key capabilities include Incremental CDC (F-A1) for capturing only changed rows, Schema Evolution Handling (F-A2) for automatically detecting schema changes, and a Health Monitor (F-A3) for observability across all active connectors.

- **MOD-B Compliance Vault** — Applies governance controls including PII Tokenization (F-B1) for protecting sensitive fields while preserving referential integrity, and Automated Retention Enforcement (F-B2) for managing the lifecycle of archived records.

All operations are recorded in an **audit log**, providing a tamper-evident trail for compliance reviews. The platform supports both real-time (CDC) and scheduled batch synchronization modes.

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-007] Health Monitor dashboard — connector status overview for admins](https://demo-jira.local/browse/DPLAT-007)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)

## Key Terminology

### What is the purpose of this platform?

The **Amisol DataPlatform Demo** is an enterprise-grade data integration and compliance solution designed to move data from operational systems into analytics and archival workloads while maintaining strict governance. It unifies real-time data movement with policy-enforced retention and privacy controls in a single, multi-tenant SaaS offering (per [$[Amisol DataPlatform Demo — Product Overview]$]).

The platform consists of two core modules:
- **MOD-A Connector Framework** — Real-time data ingestion and change capture from supported data sources
- **MOD-B Compliance Vault** — Secure archival, PII protection, and automated retention enforcement

### Who can use the connectors?

Connectors are provisioned and managed by **workspace admins**, who configure data pipelines and manage target destinations. Other user roles include **data engineers** (who build and monitor data flows) and **compliance officers** (who define retention and tokenization policies and review audit logs). Each tenant gets an isolated logical environment with its own set of workspaces, connectors, and policies (per [$[Amisol DataPlatform Demo — Product Overview]$]).

### What are the core features?

The platform's key capabilities include:

| Feature | Description |
|---------|-------------|
| **F-A1: Incremental CDC** | Captures only changed rows using native change data capture mechanisms, avoiding full table scans |
| **F-A2: Schema Evolution Handling** | Automatically detects and applies schema changes with configurable compatibility modes |
| **F-B1: PII Tokenization** | Detects and replaces sensitive fields (e.g., email, SSN) with deterministic tokens while preserving referential integrity |
| **F-B2: Automated Retention Enforcement** | Applies retention policies to archived records, transitioning them through lifecycle stages and deleting expired data |

Connectors support common source types including **Salesforce**, **SAP S/4HANA**, and **Kafka**, and are configured per workspace. Each connector emits an audit log entry for every batch processed, enabling full traceability from source to target (per [$[Connector Framework — Module Overview]$]).

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)

## System Requirements

### Purpose of the Platform

The **Amisol DataPlatform Demo** is an enterprise-grade data integration and compliance solution designed for organizations that need to move data from operational systems into analytics and archival workloads while maintaining strict governance. Per the product overview [$[Amisol DataPlatform Demo — Product Overview]$], the platform unifies real-time data movement with policy-enforced retention and privacy controls in a single, multi-tenant SaaS offering. It enables organizations to ingest data from supported sources, apply governance controls, and maintain a tamper-evident audit trail for compliance reviews.

### Who Can Use the Connectors?

The connectors are primarily used by **Workspace Admins**, who provision connectors, configure pipelines, and manage target destinations. Additionally, **Data Engineers** build and monitor data flows and handle schema evolution scenarios, while **Compliance Officers** define retention and tokenization policies and review audit logs. The Connector Configuration API requires the `workspace-admin` role and OAuth 2.0 Bearer Token authentication for programmatic access, as specified in the [$[Connector Configuration API — Reference]$].

### Core Features (System Requirements Perspective)

From a system requirements standpoint, the platform delivers the following core capabilities:

1. **MOD-A Connector Framework** — Real-time data ingestion and change capture from supported data sources, including:
   - **F-A1: Incremental CDC** — Captures only changed rows using native change data capture mechanisms, minimizing source load
   - **F-A2: Schema Evolution Handling** — Automatically detects and applies schema changes with configurable compatibility modes
   - **F-A3: Connector Health Monitoring** — Tracks connection status, data freshness, and error rates via the health-monitor-ui dashboard

2. **MOD-B Compliance Vault** — Secure archival, PII protection, and automated retention enforcement, including:
   - **F-B1: PII Tokenization** — Detects and replaces sensitive fields with deterministic tokens
   - **F-B2: Automated Retention Enforcement** — Applies retention policies and manages lifecycle stages

3. **Connector Configuration API** — Enables programmatic provisioning and management of connector instances with validation against JSON Schema Draft-7, retention period validation (30–2555 days), and duplicate name prevention

4. **Audit Logging** — All operations are recorded in a tamper-evident audit log for compliance reviews, with entries including connector name, data source type, user ID, timestamp, and retention policy version

The system requires environment variables for configuration, including API endpoints, authentication tokens, logging levels, and connection pool sizes, as documented in the connector-framework and health-monitor-ui repositories.

**Sources:**
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📋 [[DPLAT-REQ-05] Health Monitor uptime — 99.9% availability for status read API](https://demo-jira.local/browse/DPLAT-REQ-05)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)

## User Personas

The Amisol DataPlatform Demo is an enterprise-grade data integration and compliance solution designed for organizations that need to move data from operational systems into analytics and archival workloads while maintaining strict governance. The platform unifies real-time data movement with policy-enforced retention and privacy controls in a single, multi-tenant SaaS offering.

## User Personas

The platform serves three primary user roles, each with distinct responsibilities:

**Workspace Admin** – This is the primary persona for connector usage. Workspace admins provision connectors, configure data pipelines, and manage target destinations. They use guided setup wizards (e.g., [$[DPLAT-004]$] for SAP S/4HANA, [$[DPLAT-002]$] for Salesforce) to quickly configure data source connections without requiring deep technical expertise. They also monitor connector health via the [$[health-monitor-ui]$] dashboard and receive alerts when connectors experience failures.

**Data Engineer** – Builds and monitors data flows, handles schema evolution scenarios, and manages complex data transformations. This persona works with the connector framework's core infrastructure, including OAuth authentication handling and configurable retry patterns.

**Compliance Officer** – Defines retention and tokenization policies, reviews audit logs, and ensures regulatory compliance (e.g., GDPR, CCPA). This role interacts with the platform's PII tokenization and automated retention enforcement capabilities.

## Core Features

The platform consists of two modules:

- **MOD-A Connector Framework** – Provides real-time data ingestion and change capture from supported data sources (Salesforce, SAP S/4HANA, PostgreSQL, MySQL, Kafka). Key capabilities include incremental CDC, schema evolution handling, and connector health monitoring.
- **MOD-B Compliance Vault** – Applies governance controls including PII tokenization and automated retention enforcement, with all operations recorded in an audit log for compliance reviews.

## Who Can Use the Connectors?

Connectors are used primarily by **workspace admins** who provision and manage them within their tenant. Each tenant gets an isolated logical environment with its own set of workspaces, connectors, and policies. The Connector Configuration API requires OAuth 2.0 authentication with the `workspace-admin` role and `connectors:write` scope. Data engineers also interact with connectors for building and monitoring data flows.

**Sources:**
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📋 [[DPLAT-003] Salesforce connector — OAuth token refresh and session management](https://demo-jira.local/browse/DPLAT-003)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📋 [[DPLAT-REQ-13] SAP — support both SOAP and OData v4 transport](https://demo-jira.local/browse/DPLAT-REQ-13)

## Support Channels

### Purpose of the Platform

The Amisol DataPlatform Demo is an enterprise-grade data integration and compliance solution designed to move data from operational systems into analytics and archival workloads while maintaining strict governance. According to the [$[Amisol DataPlatform Demo — Product Overview]$], the platform unifies real-time data movement with policy-enforced retention and privacy controls in a single, multi-tenant SaaS offering. It consists of two core modules: **MOD-A Connector Framework** for real-time data ingestion and change capture, and **MOD-B Compliance Vault** for secure archival, PII protection, and automated retention enforcement.

### Who Can Use the Connectors?

The connectors are primarily used by **workspace administrators**, who provision connectors, configure pipelines, and manage target destinations within their tenant. Additionally, **data engineers** build and monitor data flows and handle schema evolution scenarios, while **compliance officers** define retention and tokenization policies and review audit logs (per [$[Amisol DataPlatform Demo — Product Overview]$]). The Connector Configuration API requires the `workspace-admin` role and OAuth 2.0 Bearer Token authentication for programmatic management (per [$[Connector Configuration API — Reference]$]).

### Core Features

The platform's core features include:

- **F-A1: Incremental CDC** — Captures only changed rows using native change data capture mechanisms, minimizing source load.
- **F-A2: Schema Evolution Handling** — Automatically detects and applies schema changes with configurable compatibility modes.
- **F-B1: PII Tokenization** — Detects and replaces sensitive fields with deterministic tokens, preserving referential integrity for analytics.
- **F-B2: Automated Retention Enforcement** — Applies retention policies to archived records, transitioning them through lifecycle stages and deleting them when their retention period expires.

All operations are recorded in an **audit log**, providing a tamper-evident trail for compliance reviews (based on [$[Amisol DataPlatform Demo — Product Overview]$]).

### Support Channels Aspect

From a support perspective, the platform provides a **Connector Health Monitor** (feature F-A3) as the primary interface for operations teams to track connector status, view system metrics, and receive alerts about platform components. The [$[health-monitor-ui]$] README describes this as a React-based frontend that aggregates health signals from connected systems, displays uptime statistics, and provides drill-down capabilities for investigating connectivity issues. The health monitor supports real-time status polling, automated alerting for connector failures or elevated error rates, and historical metrics for trend analysis (per [$[DPLAT-EPIC-03]$]). Support channels also include the **audit log** for tracing all configuration changes and data operations, and the **Connector Configuration API** for programmatic troubleshooting and reconfiguration without service interruption.

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [health-monitor-ui — README](https://demo-bitbucket.local/health-monitor-ui/blob/main/README.md)
- 📋 [[DPLAT-004] SAP S/4HANA connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-004)
- 📋 [[DPLAT-EPIC-01] Salesforce Connector](https://demo-jira.local/browse/DPLAT-EPIC-01)
- 📋 [[DPLAT-EPIC-03] Connector Health Monitor](https://demo-jira.local/browse/DPLAT-EPIC-03)
- 📄 [Amisol DataPlatform Demo — Product Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/eb9691cf3f86)
- 📋 [[DPLAT-002] Salesforce connector — initial setup wizard](https://demo-jira.local/browse/DPLAT-002)
- 📋 [[DPLAT-EPIC-02] SAP S/4HANA Connector](https://demo-jira.local/browse/DPLAT-EPIC-02)
- 📄 [connector-framework — README](https://demo-bitbucket.local/connector-framework/blob/main/README.md)
- 📋 [[DPLAT-012] SAP S/4HANA connector — handle large result sets via paging and stream processing](https://demo-jira.local/browse/DPLAT-012)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📄 [Connector Framework — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a332bfe04e65)
- 📄 [Release Notes — v2.4 (Planned)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/271c7e09c9fc)
- 📄 [Customer Success — Internal FAQ](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ccca2d37b14)
- 📋 [[DPLAT-023] SAP — legacy SAP ECC 6.0 compatibility mode](https://demo-jira.local/browse/DPLAT-023)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-11] Connector framework — TLS 1.3 minimum for outbound connections](https://demo-jira.local/browse/DPLAT-REQ-11)
