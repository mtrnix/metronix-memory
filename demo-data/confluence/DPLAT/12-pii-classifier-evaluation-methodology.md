---
space: DPLAT
slug: 12-pii-classifier-evaluation-methodology
title: "PII Classifier — Evaluation Methodology"
parent_slug: 03-compliance-vault-overview
labels:
  - module:compliance-vault
  - feature:F-B1
  - doc-type:methodology
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-14T11:00:00Z
version: 4
status: current
linked_jira:
  - DPLAT-005
  - DPLAT-REQ-06
  - DPLAT-REQ-17
---

# PII Classifier — Evaluation Methodology

## Overview

This document defines the evaluation methodology for the PII Classifier (Feature F-B1) within the Compliance Vault module. It establishes standardized procedures for measuring classifier performance, ensuring consistent quality assessment across tenants and data sources.

## Test Set Composition

### Language Distribution

The evaluation test set must reflect production data diversity. Each language cohort contains exactly **500 annotated documents** with the following distribution:

| Language | Documents | Characters (min) | Characters (max) |
|----------|-----------|------------------|------------------|
| English | 200 | 100 | 50,000 |
| Spanish | 100 | 100 | 50,000 |
| French | 75 | 100 | 50,000 |
| German | 75 | 100 | 50,000 |
| Portuguese | 50 | 100 | 50,000 |

### PII Category Balance

Each test set must include balanced representation across target PII categories:

- **Email addresses**: 100 instances per language
- **Phone numbers**: 80 instances per language
- **Postal addresses**: 60 instances per language
- **Names (first/last)**: 150 instances per language
- **Government IDs**: 40 instances per language
- **Credit card numbers**: 30 instances per language

### Source Diversity

Test documents must originate from at least **three distinct connector types** to ensure cross-source generalization:

- Structured data (CSV, JSON, database exports)
- Unstructured text (PDF, plain text, email bodies)
- Semi-structured logs

## Metrics

### Primary Metrics

The classifier is evaluated using precision, recall, and F1-score **per PII category**:

| Metric | Formula | Target |
|--------|---------|--------|
| Precision | TP / (TP + FP) | ≥ 0.90 |
| Recall | TP / (TP + FN) | ≥ 0.85 |
| F1-Score | 2 × (Precision × Recall) / (Precision + Recall) | ≥ 0.87 |

### Aggregate Metrics

**Macro-averaged F1** across all PII categories serves as the primary comparison metric for model versioning.

**Weighted F1** accounts for category frequency imbalances in production data.

### Error Analysis Metrics

- **False Positive Rate by Category**: Critical for minimizing over-redaction
- **Boundary Detection Accuracy**: Measures precision of character-level span detection
- **Cross-Language Leakage**: Measures unintended detections in non-target languages

## Human Review Protocol

### Reviewer Qualification

Human reviewers must complete the **PII Annotation Training** (DPLAT-005) and demonstrate inter-annotator agreement of ≥0.80 F1 before participating in evaluation.

### Review Process

1. **Blind Review**: Reviewers evaluate classifier output without knowing ground truth
2. **Gold Standard Comparison**: System automatically compares reviewer decisions against gold labels
3. **Dispute Resolution**: Disagreements between reviewer and gold standard are escalated to senior annotators

### Audit Trail

All human review sessions are recorded in the **audit log** with:

- Reviewer identity and certification level
- Timestamp of review completion
- Per-document agreement score
- Disputed items and resolution rationale

## A/B Testing Flow for Model Updates

### Phased Rollout

Model updates follow a four-stage rollout:

| Stage | Tenant Percentage | Duration | Exit Criteria |
|-------|-------------------|----------|---------------|
| Canary | 1% | 48 hours | No regression in F1 |
| Alpha | 10% | 7 days | F1 within ±0.02 of baseline |
| Beta | 50% | 14 days | F1 ≥ baseline |
| Full | 100% | — | Approval from compliance officer |

### Monitoring During A/B Test

During A/B testing, the following are tracked per tenant:

- **Detection Volume Delta**: Alert if >10% change in PII detections
- **False Positive Complaints**: Tracked via workspace admin feedback
- **Processing Latency**: Must not exceed baseline by >5%

### Rollback Triggers

Automatic rollback occurs if:

- F1 drops >0.03 in canary stage
- Critical category recall drops >0.05
- Latency increases >10%

## Retention of Evaluation Artifacts

Evaluation test sets, human review records, and A/B test results are retained for **7 years** per compliance requirements, then securely deleted.