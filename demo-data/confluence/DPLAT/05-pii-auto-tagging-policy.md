---
space: DPLAT
slug: 05-pii-auto-tagging-policy
title: "PII Auto-Tagging — Policy and Behavior"
parent_slug: 03-compliance-vault-overview
labels:
  - module:compliance-vault
  - feature:F-B1
  - doc-type:business-rules
  - source-of-truth
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-19T14:00:00Z
version: 9
status: current
linked_jira:
  - DPLAT-005
  - DPLAT-006
  - DPLAT-013
  - DPLAT-REQ-06
  - DPLAT-REQ-07
---

# PII Auto-Tagging — Policy and Behavior

## Purpose

The PII Auto-Tagging feature automatically identifies and classifies personally identifiable information within data ingested through DPLAT connectors. This capability enables compliance officers and workspace admins to apply appropriate data handling policies without manual intervention.

Auto-tagging supports regulatory requirements by ensuring PII is consistently identified across all data sources, enabling:

- Automated retention policy application
- Access control enforcement
- Audit trail generation
- Data residency compliance

## Detection model (hybrid rule+ML)

The detection engine employs a hybrid approach combining deterministic pattern matching with machine learning classification:

| Component | Description |
|-----------|-------------|
| **Rule-based detection** | Regex patterns for known PII formats (email, SSN, phone numbers, passport IDs) |
| **ML classification** | Context-aware models trained to identify names, addresses, and other sensitive entities |
| **Confidence scoring** | Each detection receives a confidence score (0.0–1.0); tagging occurs above 0.75 threshold |

The hybrid model achieves high precision while maintaining explainability for audit purposes. Rule-based detections include the matched pattern in the audit log; ML detections include the model version and feature importance summary.

## Supported languages (EN/DE/FR)

The PII detection engine supports three languages at launch:

- **EN** (English) — Full coverage for US, UK, and international English
- **DE** (German) — Optimized for DACH region naming conventions and address formats
- **FR** (French) — Coverage for France and international French

Data in unsupported languages will be processed with EN models as fallback, with reduced confidence thresholds. Workspace admins receive warnings when ingesting content in detected unsupported languages.

## Classification flow (at-ingestion)

PII classification occurs synchronously during the ingestion pipeline:

1. Connector extracts raw data from the data source
2. Content passes through the PII detection engine
3. Detected entities are tagged with metadata (type, confidence, position)
4. Tagged content proceeds to storage with classification preserved
5. Audit log entry created for each classification event

This at-ingestion approach ensures PII is identified before any downstream processing, preventing untagged sensitive data from entering analytics pipelines.

## Retention contract

**Source of truth:** The platform-wide default retention period for PII-tagged data is **30 days**, after which data is automatically anonymized or deleted according to the configured retention policy.

This retention contract applies to all tenants unless explicitly overridden. The 30-day window balances:

- Regulatory requirements for data minimization
- Operational needs for debugging and audit trails
- Customer expectations for privacy-by-design

Per-tenant retention overrides are available through the tenant configuration API. Workspace admins may request extended retention periods for specific use cases by submitting a compliance review via DPLAT-006. All retention policy changes are logged in the audit log with timestamp, actor, and justification.

## Data residency (GDPR Art. 44, BDSG)

PII-tagged data is subject to strict data residency controls:

- **GDPR Art. 44 compliance**: PII data never leaves its designated residency region without explicit consent and appropriate safeguards
- **BDSG compliance**: German-specific PII categories receive additional protection under national law
- **Region-aware routing**: Connectors automatically route data to the correct regional storage based on detected PII origin

The following table summarizes residency requirements by PII type:

| PII Type | Default Residency | Cross-border Transfer |
|----------|-------------------|----------------------|
| EU citizen data | EU region | Requires Art. 49 derogation |
| German citizen data | DE region | Restricted under BDSG |
| US citizen data | US region | State-specific rules apply |

## Override mechanism (per-tenant)

Workspace admins may override auto-tagging behavior at the tenant level through the following mechanisms:

- **Detection suppression**: Exclude specific PII types from auto-tagging for approved use cases
- **Confidence threshold adjustment**: Lower the 0.75 threshold for high-recall scenarios
- **Custom pattern rules**: Add tenant-specific regex patterns for proprietary data formats

All overrides require compliance officer approval and are scoped to the requesting tenant. Override configurations are versioned and auditable. To request an override, workspace admins must:

1. Submit a ticket referencing DPLAT-013
2. Provide business justification and data classification impact assessment
3. Define scope (specific connectors, data sources, or PII types)
4. Specify duration (temporary overrides expire after 90 days)

The compliance vault evaluates override requests against DPLAT-REQ-06 and DPLAT-REQ-07 requirements before approval.