# compliance-vault

## Overview

This repository hosts the Compliance Vault service, a core component of the MOD-B Compliance Vault module within the Amisol DataPlatform. It implements features F-B1 (PII Auto-Tagging Engine) and F-B2 (Audit Trail & Retention), providing automated data classification and compliance tracking capabilities.

The service integrates with the platform's data catalog to automatically detect and tag personally identifiable information (PII) across datasets, while maintaining immutable audit logs for regulatory compliance.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `METATRON_ENABLED` | Enable Metatron integration for data catalog sync | `true` |
| `AMISOL_DPLAT_ENV` | Deployment environment (dev/staging/prod) | `dev` |
| `COMPLIANCE_RETENTION_DAYS` | Audit log retention period | `2555` |
| `PII_PATTERN_CONFIG_PATH` | Path to PII detection patterns | `/config/pii-patterns.json` |

## Related

- JIRA: DPLAT-EPIC-04, DPLAT-EPIC-05, DPLAT-005, DPLAT-009
- Confluence: DPLAT/03-compliance-vault-overview, DPLAT/05-pii-auto-tagging-policy

## Local development

Run the service locally with `docker-compose up --build`. Execute tests via `pytest tests/` and lint with `make lint`.