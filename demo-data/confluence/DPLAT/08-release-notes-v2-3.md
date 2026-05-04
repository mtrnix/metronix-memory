---
space: DPLAT
slug: 08-release-notes-v2-3
title: "Release Notes — v2.3 (April 2026)"
parent_slug: 01-product-overview
labels:
  - doc-type:release-notes
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-15T10:00:00Z
version: 1
status: current
linked_jira:
  - DPLAT-002
  - DPLAT-005
  - DPLAT-009
  - DPLAT-010
  - DPLAT-011
---

# Release Notes — v2.3 (April 2026)

## Overview

Version 2.3 introduces significant enhancements to both the Connector Framework and Compliance Vault modules. This release focuses on improving data source onboarding, enhancing PII detection capabilities, and expanding audit capabilities for compliance officers.

| Component | Status | Priority |
|-----------|--------|----------|
| Connector Framework | Enhanced | High |
| Compliance Vault | Enhanced | High |
| Platform Core | Stable | Medium |

---

## Connector Framework

### Salesforce Onboarding Wizard

A guided wizard experience now streamlines Salesforce connector configuration, reducing setup time from approximately 45 minutes to under 10 minutes for standard use cases.

**Key capabilities:**

- **Automated OAuth configuration** — The wizard handles OAuth 2.0 handshake automatically, eliminating manual token configuration
- **Object selection preview** — Interactive preview of available Salesforce objects with row count estimates
- **Field mapping recommendations** — AI-assisted suggestions for mapping Salesforce fields to platform schema
- **Validation preview** — Test connectivity and data sampling before committing configuration

**Configuration example:**

```yaml
connector:
  type: salesforce
  version: "2.3"
  objects:
    - Account
    - Contact
    - Opportunity
  sync_mode: incremental
```

### SAP Delta Sync

The SAP connector now supports true delta synchronization, capturing only changed records since the last successful sync.

**Technical highlights:**

- **Change Document tracking** — Leverages SAP CDHDR/CDPOS tables for change detection
- **Timestamp-based cursors** — Maintains per-object sync cursors with millisecond precision
- **Resilient retry logic** — Automatic retry with exponential backoff for transient SAP connectivity issues
- **Partial failure handling** — Continues processing remaining objects when individual object sync fails

**Performance improvements:**

| Metric | v2.2 | v2.3 | Improvement |
|--------|------|------|-------------|
| Delta detection latency | 15 min | 2 min | 87% reduction |
| Memory footprint | 2.1 GB | 800 MB | 62% reduction |
| Network overhead | 450 MB/hr | 120 MB/hr | 73% reduction |

---

## Compliance Vault

### Hybrid PII Classifier

A new hybrid PII classification engine replaces the legacy regex-based classifier, combining machine learning models with deterministic pattern matching for improved accuracy.

**Architecture:**

- **ML-based detection** — Pre-trained models identify PII patterns that regex cannot capture (e.g., names, addresses, social context)
- **Deterministic fallback** — Regex patterns remain as deterministic fallback for regulated data types (SSN, credit cards, passports)
- **Confidence scoring** — Each classification includes a confidence score (0.0–1.0) for review workflows
- **Custom model training** — Workspace admins can upload labeled datasets to improve domain-specific detection

**Migration path:**

Existing data sources will automatically migrate to the hybrid classifier over a 30-day window. Workspace admins can manually trigger migration via the Compliance Vault settings panel.

See [DPLAT-005](#) for detailed classifier specifications and accuracy benchmarks.

### Audit Log Export (GA)

The audit log export feature is now Generally Available, enabling compliance officers to export historical audit data for regulatory review.

**Export capabilities:**

| Format | Description | Use Case |
|--------|-------------|----------|
| JSON Lines | Structured, machine-readable | Programmatic analysis, SIEM integration |
| CSV | Spreadsheet-compatible | Manual review, reporting |
| PDF | Human-readable, signed | Regulatory submission, legal discovery |

**Export filters:**

```bash
# Example: Export all PII access events for Q1 2026
dplat audit-export \
  --start "2026-01-01" \
  --end "2026-03-31" \
  --event-type "pii_access,pii_export,pii_delete" \
  --tenant "acme-corp" \
  --format jsonl \
  --output s3://compliance-bucket/audit-q1-2026/
```

**Retention note:** Exported audit logs maintain the same retention policy as source audit data (default: 7 years for compliance tenants).

---

## Known Issues

### DPLAT-DEF-04: Retention Discrepancy

A retention calculation discrepancy has been identified affecting tenants with custom retention policies configured before v2.0. In affected scenarios, data may be retained up to 48 hours beyond the configured retention window.

**Impact:** Low — Data is deleted within acceptable tolerance for most compliance frameworks.

**Workaround:** Tenants requiring strict retention boundaries can enable the `retention.strict_mode` feature flag, which prioritizes accuracy over performance.

**Status:** Under investigation. Target resolution: v2.4.

---

## Upgrade Notes

### Breaking Changes

None for v2.3. This release maintains backward compatibility with v2.2 configurations.

### Recommended Actions

1. **Workspace admins:** Review Salesforce connector configurations and re-run wizard for optimized settings
2. **Compliance officers:** Test audit log export functionality in staging tenants before production use
3. **Platform administrators:** Monitor SAP delta sync performance during initial delta capture window

### Rollback Procedure

In case of issues, rollback to v2.2 via:

```bash
dplat platform rollback --target "2.2.0" --confirm
```

---

## Support

For issues related to this release, please reference version 2.3 in all support tickets. Critical issues should be escalated via the DPLAT support portal with severity P1.