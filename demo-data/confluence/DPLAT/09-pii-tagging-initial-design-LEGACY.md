---
space: DPLAT
slug: 09-pii-tagging-initial-design-LEGACY
title: "PII Tagging — Initial Design (Legacy)"
parent_slug: 03-compliance-vault-overview
labels:
  - module:compliance-vault
  - feature:F-B1
  - doc-type:design
  - superseded
author: ariel@mtrnix.example
created: 2024-01-15T08:00:00Z
updated: 2024-04-12T10:00:00Z
version: 2
status: superseded
linked_jira: []
---

# PII Tagging — Initial Design (Legacy)

## Overview

This document describes the initial implementation of automatic PII detection and tagging within the Compliance Vault module. The system identifies personally identifiable information in ingested data and applies metadata tags that enable downstream governance, retention, and access control policies.

## Architecture

### Pipeline Position

The PII tagging pipeline executes **post-ingestion**, after data has been:
1. Extracted from the source connector
2. Validated for schema compliance
3. Stored in the raw data lake

This placement ensures tagging operates on stable, persisted data without blocking the ingestion path.

### Processing Flow

```
Connector → Ingestion → Raw Storage → [PII Tagging] → Tagged Dataset
                                         ↓
                                   Audit Log Entry
```

## Detection Mechanism

### Rule-Based Approach

The initial implementation uses **deterministic regex-based pattern matching** against known PII formats. Each rule consists of:

| Field | Description |
|-------|-------------|
| `pattern` | Regex pattern for matching |
| `pii_type` | Classification category |
| `confidence` | Fixed value of 0.95 |
| `redact_default` | Whether to redact by default |

### Supported PII Types

| PII Type | Pattern Example | Redact Default |
|----------|-----------------|----------------|
| SSN | `\b\d{3}-\d{2}-\d{4}\b` | true |
| Email | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | false |
| Phone (US) | `\(\d{3}\)\s*\d{3}-\d{4}` | false |
| Credit Card | `\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b` | true |
| US Zip | `\b\d{5}(-\d{4})?\b` | false |

## Language Support

**Current implementation supports English-language data only.** Regex patterns are tuned for:
- US/UK date formats (MM/DD/YYYY, DD/MM/YYYY)
- US phone number conventions
- Western name structures

Non-English data sources should be manually reviewed by the compliance officer before processing.

## Tenant Configuration

### Workspace Admin Capabilities

Workspace admins can configure:

1. **Enable/disable tagging** per data source
2. **Override redaction defaults** for specific PII types
3. **Add custom regex patterns** via the UI (validated server-side)

### Retention Policy Integration

Tagged PII automatically inherits retention rules:

| PII Sensitivity | Default Retention |
|-----------------|-------------------|
| High (SSN, CC) | 2 years |
| Medium (Email, Phone) | 5 years |
| Low (Zip code) | 7 years |

## Audit Logging

Each tagging operation generates an audit log entry:

```json
{
  "event": "pii_tagging_complete",
  "data_source_id": "ds-12345",
  "records_scanned": 10000,
  "pii_detected": {
    "email": 8542,
    "phone": 3201,
    "ssn": 0
  },
  "timestamp": "2024-03-15T14:30:00Z",
  "tenant_id": "tenant-abc"
}
```

## Performance Considerations

### Throughput

| Data Volume | Expected Latency |
|-------------|------------------|
| < 100K rows | < 5 minutes |
| 100K–1M rows | < 30 minutes |
| > 1M rows | < 2 hours |

### Resource Allocation

The tagging pipeline runs on a dedicated compute pool, isolated from ingestion workers to prevent resource contention.

## Limitations

- **No context-aware detection**: Regex matches may produce false positives (e.g., version numbers matching SSN patterns)
- **No machine learning**: Cannot detect PII without explicit patterns
- **Single-language**: English-only tuning
- **Post-hoc processing**: Tags applied after ingestion, not at capture time

## Future Enhancements (Backlog)

- ML-based detection for unstructured text
- Multi-language pattern libraries
- Real-time tagging at ingestion boundary
- Custom PII type definitions via JSON schema