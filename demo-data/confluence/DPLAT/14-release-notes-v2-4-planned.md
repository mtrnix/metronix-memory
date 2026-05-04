---
space: DPLAT
slug: 14-release-notes-v2-4-planned
title: "Release Notes — v2.4 (Planned)"
parent_slug: 01-product-overview
labels:
  - doc-type:release-notes
  - status:planned
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-25T10:00:00Z
version: 1
status: current
linked_jira:
  - DPLAT-006
  - DPLAT-008
  - DPLAT-014
  - DPLAT-019
  - DPLAT-023
---

# Release Notes — v2.4 (Planned)

## Overview

This document outlines the planned features and improvements for DPLAT version 2.4, targeting release in Q2 2026. This release focuses on expanding connector compatibility and strengthening compliance capabilities for enterprise tenants.

---

## Connector Framework Enhancements

### SAP ECC Compatibility

The Connector Framework will add native support for SAP ECC (Enterprise Central Component) data sources, enabling seamless integration with legacy SAP environments.

**Key capabilities:**

- **Native SAP ECC connector** with support for RFC/HTTP protocols
- **Idempotent extraction** with checkpoint resumption for large datasets
- **Schema auto-discovery** for SAP tables, structures, and CDS views
- **ABAP dictionary type mapping** to DPLAT native types

**Use case:** Enterprises with SAP ECC 6.0+ can now extract master data, transactional records, and custom Z-tables without custom ETL development.

**Related:** DPLAT-023

### Health Monitor Alerting

The Connector Health Monitor will support configurable alerting channels, enabling proactive operational visibility.

**Features:**

| Alert Type | Description | Severity |
|------------|-------------|----------|
| Connection Failure | Connector unable to reach data source | Critical |
| Sync Degradation | Latency exceeding threshold | Warning |
| Schema Drift | Upstream schema change detected | Warning |
| Rate Limit Exhaustion | API throttling detected | Info |

**Configuration:**

Workspace admins will configure alerting via:

```yaml
health_monitor:
  alerting:
    channels:
      - type: webhook
        url: https://hooks.example.com/dplat
        severity_filter: [critical, warning]
      - type: email
        recipients: ["ops@example.com"]
        severity_filter: [critical]
```

**Related:** DPLAT-008

---

## Compliance Vault Enhancements

### Per-Tenant Retention Overrides

Compliance Vault will support tenant-level retention policy overrides, enabling organizations with complex regulatory requirements to customize data lifecycle management.

**Policy hierarchy:**

1. **Platform default** — Applied when no override exists
2. **Tenant override** — Configured by tenant admin, supersedes platform default
3. **Workspace override** — Fine-grained control per workspace, supersedes tenant override

**Retention configuration:**

```json
{
  "retention_policy": {
    "scope": "tenant",
    "data_categories": {
      "pii": { "retention_days": 2555, "disposal_method": "cryptographic_erase" },
      "audit_log": { "retention_days": 3650, "disposal_method": "archive_then_delete" },
      "operational": { "retention_days": 365, "disposal_method": "soft_delete" }
    }
  }
}
```

**Compliance benefit:** Enables alignment with GDPR Article 17, CCPA, HIPAA, and industry-specific retention mandates without requiring separate platform instances.

**Related:** DPLAT-006

### Encrypted Audit Archive

A new audit archive feature will provide tamper-evident, encrypted storage of historical audit logs, addressing long-term compliance retention requirements.

**Technical specifications:**

- **Encryption:** AES-256-GCM with per-archive key derivation
- **Key management:** Customer-managed keys (CMK) via AWS KMS, Azure Key Vault, or HashiCorp Vault
- **Integrity:** SHA-256 chain-of-custody with Merkle root verification
- **Storage:** Object storage (S3, Azure Blob, GCS) with versioning enabled

**Access model:**

| Role | Archive Read | Archive Write | Key Management |
|------|--------------|---------------|----------------|
| Compliance Officer | ✅ | ❌ | ✅ |
| Workspace Admin | ✅ | ❌ | ❌ |
| Auditor (External) | ✅ | ❌ | ❌ |
| System | ❌ | ✅ | ✅ |

**Related:** DPLAT-014

---

## Additional Improvements

### Performance

- **DPLAT-019:** Query engine optimization reducing p99 latency by 40% for multi-connector joins

---

## Feedback & Testing

This feature set will enter beta testing in March 2026. Tenants interested in early access should contact their customer success manager or submit a request via the DPLAT portal.

**Known limitations:**

- SAP ECC connector requires target system version 6.0 or later
- Encrypted audit archive requires object storage with versioning enabled
- Retention overrides apply to data ingested after policy configuration