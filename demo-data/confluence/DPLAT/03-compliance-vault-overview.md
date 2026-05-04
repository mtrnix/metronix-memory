---
space: DPLAT
slug: 03-compliance-vault-overview
title: "Compliance Vault — Module Overview"
parent_slug: 01-product-overview
labels:
  - module:compliance-vault
  - doc-type:overview
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-08T10:00:00Z
version: 3
status: current
linked_jira:
  - DPLAT-EPIC-04
  - DPLAT-EPIC-05
---

# Compliance Vault — Module Overview

The Compliance Vault (MOD-B) is the privacy and governance layer of DataPlatform. It enables tenants to identify, classify, and track access to sensitive data across all connected data sources, ensuring alignment with regulatory requirements such as GDPR and the German BDSG.

## Regulatory Framing

Organizations operating in the European Union must comply with the General Data Protection Regulation (GDPR), which mandates:

- Lawful processing of personal data
- Data minimization and purpose limitation
- Rights of data subjects (access, rectification, erasure)
- Accountability and documentation obligations

German companies must additionally satisfy the Bundesdatenschutzgesetz (BDSG), which imposes stricter requirements on employee data processing and mandates specific documentation practices for automated decision-making.

The Compliance Vault addresses these obligations through automated PII detection and immutable audit trails.

## Feature: PII Auto-Tagging (F-B1)

The PII Auto-Tagging feature automatically identifies and classifies personally identifiable information within ingested datasets.

### How It Works

When a connector ingests data from a data source, the PII Auto-Tagging engine:

1. Scans column values using pattern-matching rules
2. Applies machine-learning classifiers for probabilistic detection
3. Tags identified fields with standardized PII categories
4. Propagates tags to downstream reports and dashboards

### Supported PII Categories

| Category | Example Values | Detection Method |
|----------|---------------|------------------|
| Email Address | user@example.com | Regex pattern |
| Phone Number | +49 30 1234567 | Regex pattern |
| National ID | German Personalausweis | Format validation |
| Name | First/Last name | ML classifier |
| Address | Street, postal code | Combined rules |
| IP Address | 192.168.1.100 | Regex pattern |

### Configuration

Workspace admins can customize PII detection rules through the Compliance Vault interface:

- Enable or disable specific PII categories
- Define custom regex patterns for organization-specific identifiers
- Set confidence thresholds for ML-based detection
- Create allowlists for false-positive suppression

## Feature: Audit Log Export (F-B2)

The Audit Log Export feature provides compliance officers with access to immutable records of all data access and modification events within the tenant.

### Logged Events

The Compliance Vault captures the following event types:

- **Data Access**: User viewed or exported data from reports, dashboards, or datasets
- **Data Modification**: User created, updated, or deleted data objects
- **Permission Changes**: User was granted or revoked access to workspaces or datasets
- **Configuration Changes**: Connector settings, PII rules, or retention policies were modified
- **Authentication Events**: User login, logout, and failed authentication attempts

### Export Formats

Compliance officers can export audit logs in multiple formats:

- **JSON**: Machine-readable format for automated processing
- **CSV**: Spreadsheets for manual review and analysis
- **PDF**: Human-readable reports with digital signatures for legal proceedings

### Audit Log Retention

Audit logs are retained according to the tenant's configured retention policy. For specific retention periods and regulatory requirements, see the [Retention Policy Reference](05-retention-policy-reference).

## User Roles and Permissions

The Compliance Vault defines three specialized roles:

| Role | Capabilities | Typical Assignee |
|------|-------------|------------------|
| Compliance Officer | View and export audit logs, configure PII rules | Legal/Privacy team |
| Workspace Admin | Manage PII tagging for their workspace | Data team lead |
| Data Steward | Review PII classifications, request corrections | Subject matter expert |

## Integration with Other Modules

The Compliance Vault integrates seamlessly with other DataPlatform modules:

- **MOD-A (Data Connectors)**: PII tagging occurs at ingestion time
- **MOD-C (Data Catalog)**: PII tags appear in catalog metadata and search results
- **MOD-D (Access Control)**: PII-sensitive datasets can have restricted access policies
- **MOD-E (Data Quality)**: PII fields can be excluded from quality checks to prevent exposure

## Getting Started

To enable the Compliance Vault in your tenant:

1. Navigate to **Settings → Compliance Vault**
2. Enable PII Auto-Tagging for your workspaces
3. Configure baseline PII detection rules
4. Review the audit log to establish a baseline
5. Set up automated audit log exports for your compliance workflow

For detailed configuration guidance, see the [Compliance Vault User Guide](04-compliance-vault-user-guide).