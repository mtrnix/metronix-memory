# pii-classifier-service

## Overview

The PII Classifier Service is a core component of the **MOD-B Compliance Vault** module, implementing feature **F-B1 (PII Auto-Detection)**. This microservice analyzes data payloads to identify, classify, and tag Personally Identifiable Information (PII) patterns such as email addresses, social security numbers, credit card numbers, phone numbers, and other sensitive identifiers.

The service provides real-time classification capabilities that feed into the broader compliance pipeline, enabling automatic data tagging, policy enforcement, and audit trail generation. It supports configurable pattern matching rules, sensitivity level assignment, and optional redaction preview capabilities to help teams maintain GDPR, CCPA, and HIPAA compliance across the DataPlatform ecosystem.

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `PII_PATTERNS_CONFIG_PATH` | Path to YAML/JSON file containing regex patterns for PII detection | `/app/config/pii_patterns.yaml` |
| `REDACTION_ENABLED` | Whether to provide redacted output alongside classification | `false` |
| `MAX_PAYLOAD_SIZE` | Maximum request body size in bytes | `1048576` |
| `REDIS_URL` | Redis connection URL for caching classification results | `redis://localhost:6379` |
| `CONFIDENCE_THRESHOLD` | Minimum confidence score to flag as PII (0.0-1.0) | `0.8` |

## Related

**JIRA:** DPLAT-EPIC-04, DPLAT-005, DPLAT-006, DPLAT-013, DPLAT-031, DPLAT-033

**Confluence:** DPLAT/05-pii-auto-tagging-policy, DPLAT/12-pii-classifier-evaluation-methodology

## Local development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the service
export LOG_LEVEL=DEBUG
uvicorn main:app --reload --port 8001

# Run tests
pytest tests/ -v

# Run linter
flake8 src/ --max-line-length=120
```