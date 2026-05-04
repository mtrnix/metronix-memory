---
space: DPLAT
slug: 01-product-overview
title: "Amisol DataPlatform Demo — Product Overview"
parent_slug: null
labels:
  - doc-type:overview
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-01T10:00:00Z
version: 5
status: current
linked_jira: []
---

# Amisol DataPlatform Demo — Product Overview

Amisol DataPlatform Demo is an enterprise-grade data integration and compliance solution designed for organizations that must move data from operational systems into analytics and archival workloads while maintaining strict governance. The platform unifies real-time data movement with policy-enforced retention and privacy controls in a single, multi-tenant SaaS offering.

## Architecture at a Glance

The platform consists of two modules that work together:

| Module | Purpose |
|--------|---------|
| **MOD-A Connector Framework** | Real-time data ingestion and change capture from supported data sources |
| **MOD-B Compliance Vault** | Secure archival, PII protection, and automated retention enforcement |

Each **tenant** gets an isolated logical environment with its own set of workspaces, connectors, and policies. A **workspace admin** provisions connectors and manages data pipelines, while a **compliance officer** defines and audits retention and privacy policies.

## MOD-A: Connector Framework

The Connector Framework ingests change events from supported **data sources** and delivers them to downstream targets with low latency and exactly-once semantics.

### Key Capabilities

- **F-A1: Incremental CDC** — Captures only changed rows using native change data capture mechanisms, avoiding full table scans and minimizing source load.
- **F-A2: Schema Evolution Handling** — Automatically detects and applies schema changes (added/removed columns, type promotions) with configurable compatibility modes.

Connectors are configured per workspace and support common source types including PostgreSQL, MySQL, and Kafka. Each connector emits an **audit log** entry for every batch processed, enabling traceability from source to target.

## MOD-B: Compliance Vault

The Compliance Vault receives data from MOD-A pipelines and applies governance controls required by regulation and internal policy.

### Key Capabilities

- **F-B1: PII Tokenization** — Detects and replaces sensitive fields (e.g., email, SSN) with deterministic tokens, preserving referential integrity for analytics while protecting privacy.
- **F-B2: Automated Retention Enforcement** — Applies retention policies to archived records, transitioning them through lifecycle stages and deleting them when their retention period expires.

All vault operations are recorded in the **audit log**, providing a tamper-evident trail for compliance reviews.

## Primary User Roles

| Role | Responsibilities |
|------|------------------|
| **Workspace Admin** | Provisions connectors, configures pipelines, manages target destinations |
| **Data Engineer** | Builds and monitors data flows, handles schema evolution scenarios |
| **Compliance Officer** | Defines retention and tokenization policies, reviews audit logs |

## Typical Data Flow

1. Workspace admin configures a **connector** for a supported **data source**.
2. MOD-A ingests changes via **F-A1: Incremental CDC** and applies **F-A2: Schema Evolution Handling** as needed.
3. Data is delivered to the Compliance Vault.
4. MOD-B applies **F-B1: PII Tokenization** to sensitive fields.
5. **F-B2: Automated Retention Enforcement** manages the lifecycle of archived records.
6. All steps are recorded in the **audit log** for compliance review.

## Getting Started

To begin, create a tenant and workspace, then add your first connector. Refer to the Connector Framework and Compliance Vault documentation for detailed setup guides and feature-specific configuration options.

For questions about retention policy defaults and compliance certifications, consult the dedicated policy documentation — this overview page is not the source of truth for policy parameters.