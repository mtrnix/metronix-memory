# 3.1  Classifier configuration

> Defining rules for automated PII detection.

## Rule Definition

To create a new classifier within the PII Auto-Tagging feature, you focus on defining the **detection rules** that govern how the system identifies sensitive data. The classifier uses a **hybrid rule + ML pipeline** that executes at ingestion time, as documented in [$[PII Auto-Tagging — Policy and Behavior]$] and implemented in [$[DPLAT-005]$].

### How to Define Rules for a New Classifier

1. **Pattern-Based Rules (Regex)**: Define deterministic regex patterns for known PII formats. The system supports patterns for email addresses, phone numbers, national IDs, IP addresses, and other structured identifiers. These patterns are configured in the `pii_patterns.yaml` file (referenced by the `PII_PATTERNS_CONFIG_PATH` environment variable in the [$[pii-classifier-service README]$]).

2. **ML Classification Rules**: For context-aware detection (names, addresses), the system uses machine learning models trained for English, German, and French. The ML component assigns a confidence score (0.0–1.0) to each detection.

3. **Confidence Threshold**: Set the minimum confidence score for tagging. The default threshold is **0.75** (per [$[PII Auto-Tagging — Policy and Behavior]$]), but this can be adjusted per tenant. The service-level default is 0.8 (per the README).

### Adjusting Sensitivity Levels

You can adjust sensitivity through two mechanisms:

- **Confidence threshold adjustment**: Lower the threshold (e.g., to 0.6) for high-recall scenarios, or raise it (e.g., to 0.9) for high-precision requirements. This is configured via the `CONFIDENCE_THRESHOLD` environment variable or through the tenant override mechanism.
- **Per-tenant overrides**: Workspace admins can submit a ticket referencing [$[DPLAT-013]$] to request custom sensitivity levels. All overrides require compliance officer approval and expire after 90 days (per [$[PII Auto-Tagging — Policy and Behavior]$]).

### Data Types That Can Be Tagged

The classifier supports the following PII categories out of the box (per [$[Compliance Vault — Module Overview]$]):

| Category | Example | Detection Method |
|----------|---------|------------------|
| Email Address | user@example.com | Regex pattern |
| Phone Number | +49 30 1234567 | Regex pattern |
| National ID | German Personalausweis | Format validation |
| Name | First/Last name | ML classifier |
| Address | Street, postal code | Combined rules |
| IP Address | 192.168.1.100 | Regex pattern |
| Credit Card Number | 4111-1111-1111-1111 | Regex pattern |
| Government ID | Various formats | Format validation |

Additionally, workspace admins can define **custom regex patterns** for organization-specific identifiers through the Compliance Vault interface or by adding patterns to the YAML configuration file.

### Important Considerations

- **Language support**: The classifier supports EN, DE, and FR. Unsupported languages fall back to English models with reduced confidence (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Known limitation**: The classifier may mislabel 4-digit Austrian postal codes as PII (see [$[DPLAT-DEF-06]$]). A workaround involves adding "postal_code" to the exclusion pattern list.
- **Document size limit**: The service has a `MAX_PAYLOAD_SIZE` of 1MB (1,048,576 bytes). Documents exceeding this may cause crashes (see [$[DPLAT-DEF-16]$]).
- **Override mechanism**: Workspace admins can review and override classifier decisions through the review interface implemented in [$[DPLAT-013]$], with all overrides logged in the audit trail.

**Sources:**
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Pattern Matching

To create a new classifier focused on **Pattern Matching**, you configure the PII Classifier Service by defining regex-based detection rules in a YAML/JSON configuration file. According to [$[pii-classifier-service]$], the service uses the environment variable `PII_PATTERNS_CONFIG_PATH` (default: `/app/config/pii_patterns.yaml`) to load pattern matching rules. You create a new classifier by:

1. **Editing the pattern configuration file** – Add new regex patterns for the PII types you want to detect. The system supports deterministic pattern matching for known formats like email addresses, phone numbers, national IDs, and IP addresses (per [$[Compliance Vault — Module Overview]$]).
2. **Setting the confidence threshold** – The `CONFIDENCE_THRESHOLD` environment variable (default 0.8) determines the minimum confidence score for flagging content as PII. For pattern-based detection, confidence is typically high (0.9+) because regex matches are exact.
3. **Enabling the hybrid pipeline** – The classifier combines rule-based detection with ML classification (per [$[PII Auto-Tagging — Policy and Behavior]$]). Pattern matching runs first, then ML models handle context-sensitive entities like names and addresses.

## Adjusting Sensitivity Levels

You can adjust sensitivity levels through several mechanisms:

- **Global confidence threshold** – Set `CONFIDENCE_THRESHOLD` (0.0–1.0) in the service configuration. Lowering it (e.g., to 0.75) increases recall but may introduce false positives.
- **Per-tenant overrides** – Workspace admins can adjust the 0.75 threshold for high-recall scenarios, subject to compliance officer approval (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Custom pattern rules** – Add tenant-specific regex patterns for proprietary data formats, with all overrides versioned and auditable.

## Data Types That Can Be Tagged

The pattern matching classifier supports the following data types (per [$[Compliance Vault — Module Overview]$] and [$[PII Classifier — Evaluation Methodology]$]):

| PII Category | Detection Method | Example |
|--------------|------------------|---------|
| Email Address | Regex pattern | user@example.com |
| Phone Number | Regex pattern | +49 30 1234567 |
| National ID | Format validation | German Personalausweis |
| IP Address | Regex pattern | 192.168.1.100 |
| Credit Card Number | Regex pattern | 4111-1111-1111-1111 |
| Government ID | Format validation | Passport numbers |

**Note:** The classifier currently has a known issue where Austrian-style 4-digit postal codes (e.g., "1010") are incorrectly flagged as PII-Address with high confidence (0.92), while German 5-digit codes are handled correctly (per [$[DPLAT-DEF-06]$]). This bug is open and being investigated.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)

## Regex Config

`⚠ stale`

To create a new classifier using the **Regex Config** approach, you need to define deterministic regex-based pattern matching rules. According to the legacy design documented in [$[PII Tagging — Initial Design (Legacy)]$], each rule consists of four fields:

- **`pattern`**: The regex pattern for matching (e.g., `\b\d{3}-\d{2}-\d{4}\b` for SSN)
- **`pii_type`**: The classification category (e.g., "SSN", "Email", "Credit Card")
- **`confidence`**: A fixed confidence value (default is `0.95` for regex matches)
- **`redact_default`**: Whether to redact by default (`true` or `false`)

The configuration is stored in a YAML or JSON file specified by the `PII_PATTERNS_CONFIG_PATH` environment variable (default: `/app/config/pii_patterns.yaml` for the pii-classifier-service, or `/config/pii-patterns.json` for the compliance-vault service). You can add new patterns directly to this file.

## Adjusting Sensitivity Levels

Sensitivity levels are controlled through two mechanisms:

1. **Confidence Threshold**: The `CONFIDENCE_THRESHOLD` environment variable (range 0.0–1.0, default `0.8`) sets the minimum confidence score required to flag content as PII. Lowering this value increases sensitivity (more detections, more false positives); raising it decreases sensitivity.

2. **Retention Policy Integration**: Per the legacy design, tagged PII automatically inherits retention rules based on sensitivity:
   - **High** (SSN, Credit Card): 2 years default retention
   - **Medium** (Email, Phone): 5 years default retention
   - **Low** (Zip code): 7 years default retention

Workspace admins can also override redaction defaults for specific PII types via the UI (per [$[PII Tagging — Initial Design (Legacy)]$]).

## Data Types That Can Be Tagged

The regex-based classifier supports the following PII types out of the box (based on the legacy design):

| PII Type | Pattern Example |
|----------|-----------------|
| SSN | `\b\d{3}-\d{2}-\d{4}\b` |
| Email | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` |
| Phone (US) | `\(\d{3}\)\s*\d{3}-\d{4}` |
| Credit Card | `\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b` |
| US Zip | `\b\d{5}(-\d{4})?\b` |

**Important limitation**: The legacy regex-only approach supports **English-language data only** and is tuned for US/UK date formats, US phone conventions, and Western name structures. The newer hybrid pipeline (implemented in [$[DPLAT-005]$]) adds ML-based detection for EN/DE/FR languages, but the pure Regex Config approach remains English-only. Workspace admins can also add custom regex patterns via the UI, which are validated server-side.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)

## Dictionary Setup

To create a new classifier, you configure the PII detection patterns through a **dictionary-based approach** using a YAML/JSON file. According to [$[pii-classifier-service]$], the primary configuration is set via the environment variable `PII_PATTERNS_CONFIG_PATH`, which defaults to `/app/config/pii_patterns.yaml`. This file contains the regex patterns that define what data types the classifier can detect and tag.

### How to Create a New Classifier

1. **Define your pattern dictionary**: Create or modify the YAML/JSON file at the path specified by `PII_PATTERNS_CONFIG_PATH`. This file serves as the dictionary of patterns the classifier uses to identify sensitive data.
2. **Set the confidence threshold**: Configure `CONFIDENCE_THRESHOLD` (default 0.8) to control the minimum confidence score required to flag content as PII. Per [$[PII Auto-Tagging — Policy and Behavior]$], the default tagging threshold is 0.75, but you can adjust this per-tenant through the override mechanism.
3. **Deploy the service**: Run the classifier service with your configuration file. The service will load the dictionary at startup and apply the patterns during ingestion.

### Adjusting Sensitivity Levels

You can adjust sensitivity levels through two mechanisms:

- **Global threshold**: Modify the `CONFIDENCE_THRESHOLD` environment variable (range 0.0–1.0). Lower values increase recall (more detections) but may reduce precision.
- **Per-tenant overrides**: Workspace admins can request confidence threshold adjustments through the override mechanism described in [$[PII Auto-Tagging — Policy and Behavior]$]. This requires compliance officer approval and is scoped to specific tenants. Overrides expire after 90 days unless renewed.

### Data Types That Can Be Tagged

The dictionary-based classifier supports tagging the following PII data types, as defined in the evaluation methodology [$[PII Classifier — Evaluation Methodology]$]:

| PII Category | Examples |
|-------------|----------|
| **Email addresses** | Standard email formats |
| **Phone numbers** | International and local formats |
| **Postal addresses** | Street addresses, cities, postal codes |
| **Names (first/last)** | Personal names in EN, DE, FR |
| **Government IDs** | SSN, passport numbers, Personalausweisnummer |
| **Credit card numbers** | Major card network formats |

The detection uses a hybrid rule+ML approach: regex patterns from the dictionary handle known formats (email, SSN, credit cards), while ML models identify context-sensitive entities (names, addresses). The dictionary file primarily defines the regex patterns, while ML models are trained separately for EN, DE, and FR languages.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)

## Logic Rules

`⚠ conflict`

To create a new classifier using the **Logic Rules** approach in the PII Classifier Service, you work with the **rule-based detection** component of the hybrid engine. According to [$[PII Auto-Tagging — Policy and Behavior]$], the rule-based detection uses **regex patterns for known PII formats** such as email addresses, SSNs, phone numbers, and passport IDs. The configuration is managed through a YAML/JSON file specified by the `PII_PATTERNS_CONFIG_PATH` environment variable (default: `/app/config/pii_patterns.yaml`), as documented in the [$[pii-classifier-service README]$].

To add a new classifier rule:
1. Edit the `pii_patterns.yaml` file and define a new regex pattern entry with a unique identifier, the regex pattern itself, and an associated PII category.
2. Restart the service or trigger a configuration reload.
3. The new rule will be evaluated during the ingestion pipeline alongside existing patterns.

## Adjusting Sensitivity Levels

Sensitivity levels are controlled through the **confidence threshold** mechanism. Per [$[PII Auto-Tagging — Policy and Behavior]$], each detection receives a confidence score (0.0–1.0), and tagging occurs above a **0.75 threshold** by default. You can adjust sensitivity in two ways:

- **Globally**: Modify the `CONFIDENCE_THRESHOLD` environment variable (default 0.8 per the README, though the policy document states 0.75 — note this discrepancy between sources). Lowering the threshold increases recall (more items flagged) but may increase false positives.
- **Per-tenant**: Workspace admins can request a confidence threshold adjustment via the override mechanism (requires compliance officer approval and a ticket referencing [$[DPLAT-013]$]). This is useful for high-recall scenarios.

## Data Types That Can Be Tagged

The classifier supports tagging the following PII categories via logic rules, as specified in the [$[PII Classifier — Evaluation Methodology]$]:

- **Email addresses**
- **Phone numbers**
- **Postal addresses** (though note the known bug [$[DPLAT-DEF-06]$] where Austrian 4-digit postal codes are incorrectly flagged)
- **Names (first/last)**
- **Government IDs** (e.g., passport IDs, SSNs)
- **Credit card numbers**

Additionally, the rule-based engine can be extended with **custom tenant-specific regex patterns** for proprietary data formats, as described in the override mechanism section of the policy document. The system supports detection in **English, German, and French** languages out of the box, with English as the fallback for unsupported languages.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [Salesforce Connector — Business Rules](https://demo-confluence.local/wiki/spaces/DPLAT/pages/a8108bdde70b)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Sensitivity Tuning

`⚠ stale`

### Creating a New Classifier

The PII Classifier is not created as a standalone entity but is configured as part of the Compliance Vault module (MOD-B). To enable and configure the classifier:

1. Navigate to **Settings → Compliance Vault** in your workspace
2. Enable **PII Auto-Tagging** for your workspaces
3. Configure baseline PII detection rules through the Compliance Vault interface

Per [$[Compliance Vault — Module Overview]$], workspace admins can customize detection rules by enabling or disabling specific PII categories, defining custom regex patterns, setting confidence thresholds for ML-based detection, and creating allowlists for false-positive suppression.

### Adjusting Sensitivity Levels

Sensitivity tuning is primarily controlled through the **confidence threshold** mechanism:

- The `CONFIDENCE_THRESHOLD` environment variable (default: `0.8`) sets the minimum confidence score required to flag data as PII, as documented in the [$[pii-classifier-service]$] README. This value ranges from 0.0 to 1.0.
- Lowering the threshold increases sensitivity (more items flagged as PII, but potentially more false positives)
- Raising the threshold decreases sensitivity (fewer items flagged, but higher precision)

For more granular control, workspace admins can:
- **Override classifier decisions** per field through the review interface (implemented in [$[DPLAT-013]$]), where all overrides are recorded in the audit log and used as training feedback
- **Configure per-category sensitivity** by enabling/disabling specific PII categories in the Compliance Vault settings
- **Set custom regex patterns** for organization-specific identifiers

The evaluation methodology in [$[PII Classifier — Evaluation Methodology]$] establishes target metrics: precision ≥ 0.90, recall ≥ 0.85, and F1-score ≥ 0.87 per PII category. The non-functional requirement [$[DPLAT-REQ-06]$] mandates even stricter precision ≥ 0.95 on the EN/DE/FR validation set.

### Data Types That Can Be Tagged

The classifier supports the following PII categories, as defined in the [$[Compliance Vault — Module Overview]$]:

| Category | Detection Method |
|----------|-----------------|
| Email Address | Regex pattern |
| Phone Number | Regex pattern |
| National ID (e.g., German Personalausweis) | Format validation |
| Name (First/Last) | ML classifier |
| Address (Street, postal code) | Combined rules |
| IP Address | Regex pattern |

The hybrid pipeline (implemented in [$[DPLAT-005]$]) combines deterministic regex-based rules with ML-based entity recognition, supporting English, German, and French languages out of the box. This replaced the legacy rule-only post-ingest approach, achieving 18.2% recall improvement with 0.92 precision in validation testing.

**Key takeaway for Sensitivity Tuning**: Adjust the `CONFIDENCE_THRESHOLD` environment variable (0.0–1.0) to control overall sensitivity, use the review interface to override individual classifications, and leverage per-category enable/disable settings for targeted tuning. The default threshold of 0.8 balances detection coverage with precision requirements.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## False Positive Control

`⚠ stale`

### Creating a New Classifier

To create a new classifier instance, you use the **Connector Configuration API** ([$[Connector Configuration API — Reference]$]). Send a `POST` request to `/api/v1/connectors` with an OAuth 2.0 Bearer Token and the `workspace-admin` role. The request body must include the connector name, type, data source details, and critically, the `pii_handling` section where you enable masking and specify excluded fields. For example:

```json
{
  "name": "Salesforce Production",
  "type": "salesforce",
  "data_source": { "instance_url": "https://myorg.salesforce.com", "api_version": "v58.0" },
  "pii_handling": { "masking_enabled": true, "excluded_fields": ["SSN", "credit_card"] }
}
```

The API returns a `201 Created` response with the connector ID, status, and creation timestamp.

### Adjusting Sensitivity Levels

Sensitivity is controlled through the **`CONFIDENCE_THRESHOLD`** environment variable in the PII Classifier Service ([$[pii-classifier-service]$]). This variable accepts a value between `0.0` and `1.0` (default: `0.8`). Lowering the threshold increases sensitivity (more items flagged as PII, but with higher false positive risk). Raising it reduces false positives but may miss genuine PII. The evaluation methodology ([$[PII Classifier — Evaluation Methodology]$]) sets target precision ≥ 0.90 and recall ≥ 0.85 per PII category, with a macro-averaged F1 target of ≥ 0.87.

### Data Types That Can Be Tagged

The classifier supports tagging the following PII types, as defined in the legacy design ([$[PII Tagging — Initial Design (Legacy)]$]) and confirmed by the evaluation methodology:

- **Email addresses** (100 instances per language in test sets)
- **Phone numbers** (80 instances per language)
- **Postal addresses** (60 instances per language)
- **Names (first/last)** (150 instances per language)
- **Government IDs** (40 instances per language)
- **Credit card numbers** (30 instances per language)
- **SSN** (Social Security Numbers)
- **US Zip codes**

The hybrid rule + ML pipeline (implemented in [$[DPLAT-005]$]) supports English, German, and French out of the box, with a requirement of precision ≥ 0.95 and recall ≥ 0.90 on the EN/DE/FR validation set ([$[DPLAT-REQ-06]$]).

### False Positive Control Specifically

For **False Positive Control**, the system provides a dedicated **False-Positive Review Queue** ([$[DPLAT-032]$]). As a compliance officer, you can:

1. **Access the queue**: Navigate to the False-Positive Review Queue to see a list of flagged items with their source field, detected PII type, and confidence score.
2. **Bulk actions**: Select multiple items using checkboxes and perform:
   - **Bulk Approve** — confirms items as true PII, retains the PII tag, and continues applying retention policies.
   - **Bulk Reject** — removes the PII tag from the data, removes items from the queue, and logs the action in the audit log.
3. **Override individual decisions**: Workspace admins can also review and override any classifier decision via the review interface ([$[DPLAT-013]$]), selecting an alternative PII category from the supported taxonomy. All overrides are recorded in the audit log with timestamp, user identity, original classification, and new classification.

Additionally, the evaluation methodology ([$[PII Classifier — Evaluation Methodology]$]) tracks **False Positive Rate by Category** as a critical metric for minimizing over-redaction, and the A/B testing flow includes monitoring for **False Positive Complaints** tracked via workspace admin feedback, with automatic rollback triggers if F1 drops more than 0.03 in the canary stage.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## Thresholds

### How to Create a New Classifier

Creating a new PII classifier is not a manual setup process—the classifier is a pre-built microservice component of the **MOD-B Compliance Vault** module. To deploy it, you configure the **pii-classifier-service** (per [GITHUB] README) by setting environment variables. The key configuration for thresholds is:

- **`CONFIDENCE_THRESHOLD`** (default: `0.8`): This is the minimum confidence score (0.0–1.0) required for the system to flag content as PII. You can adjust this value when starting the service.

The classifier uses a hybrid rule+ML pipeline that runs **at ingestion time** (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior). It scans data as it enters through connectors, applying regex patterns and ML models to detect sensitive information.

### How to Adjust Sensitivity Levels

Sensitivity is controlled through **confidence thresholds** at two levels:

1. **Service-level threshold** (`CONFIDENCE_THRESHOLD`): Set globally via environment variable (default 0.8). Lowering this value (e.g., to 0.75) increases recall but may introduce more false positives. Raising it increases precision.

2. **Per-tenant override** (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior): Workspace admins can adjust the **0.75 threshold** for high-recall scenarios through the Compliance Vault interface. This requires compliance officer approval and is scoped to the requesting tenant.

The system also has a **default tagging threshold of 0.75** for the hybrid model (per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior), meaning detections above this score are tagged. The service-level `CONFIDENCE_THRESHOLD` of 0.8 is more conservative by default.

### What Data Types Can Be Tagged

The classifier supports the following PII categories (per [CONFLUENCE] Compliance Vault — Module Overview and PII Auto-Tagging — Policy and Behavior):

| Category | Detection Method |
|----------|-----------------|
| Email Address | Regex pattern |
| Phone Number | Regex pattern |
| National ID (e.g., German Personalausweis) | Format validation |
| Name (first/last) | ML classifier |
| Address (street, postal code) | Combined rules |
| IP Address | Regex pattern |
| Credit Card Numbers | Regex pattern |
| Social Security Numbers | Regex pattern |
| Government IDs | Pattern matching |

**Important threshold-related note**: The classifier currently has a known bug ([JIRA] DPLAT-DEF-06) where **4-digit Austrian postal codes** (e.g., "1010") are misclassified as PII with 0.92 confidence, while 5-digit German postal codes are correctly classified as non-PII. This is an open issue affecting the address detection threshold behavior.

### Summary for Thresholds Subsection

To configure thresholds for the PII classifier:
- **Primary threshold**: Set `CONFIDENCE_THRESHOLD` (0.0–1.0) in the service configuration (default 0.8)
- **Override mechanism**: Workspace admins can lower the tagging threshold to 0.75 per tenant with compliance approval
- **Impact**: Lower thresholds increase recall (more PII detected) but risk false positives; higher thresholds increase precision but may miss borderline cases
- **Current limitation**: The 4-digit Austrian postal code false positive (0.92 confidence) indicates the address detection threshold may need tuning for specific regional formats

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Scoring

To create a new classifier with a focus on **Scoring**, you configure the **confidence threshold** that determines how the classifier scores and flags data as PII. The primary scoring mechanism is controlled via the `CONFIDENCE_THRESHOLD` environment variable, which sets the minimum confidence score (from 0.0 to 1.0) required for the classifier to tag a piece of data as PII. By default, this threshold is set to **0.8** ([GITHUB] pii-classifier-service README). Any detection with a confidence score below this value is ignored.

### Adjusting Sensitivity Levels

You can adjust sensitivity levels by modifying the `CONFIDENCE_THRESHOLD` value:
- **Lower the threshold** (e.g., to 0.6) to make the classifier more sensitive — it will flag more potential PII, including borderline cases. This increases recall but may introduce more false positives.
- **Raise the threshold** (e.g., to 0.95) to make the classifier less sensitive — only high-confidence detections are tagged. This increases precision but may miss some valid PII.

Additionally, workspace admins can **override individual classifier decisions** through a review interface, where they can manually change the PII category assigned to a field. These overrides are recorded in the audit log and used as training feedback to improve future scoring ([JIRA] DPLAT-013).

### Data Types That Can Be Tagged

The classifier can tag the following data types, each with its own scoring method:

| Data Type | Detection Method |
|-----------|-----------------|
| Email Address | Regex pattern |
| Phone Number | Regex pattern |
| National ID (e.g., German Personalausweis) | Format validation |
| Name (First/Last) | ML classifier |
| Address (Street, postal code) | Combined rules |
| IP Address | Regex pattern |
| Credit Card Number | Regex pattern |

([CONFLUENCE] Compliance Vault — Module Overview)

The scoring system uses a **hybrid rule + ML pipeline** that executes at ingestion time. Regex-based detections typically produce high-confidence scores (near 1.0), while ML-based detections (e.g., names) may have lower confidence scores depending on context. The evaluation methodology requires precision ≥ 0.90 and recall ≥ 0.85 per PII category, with a target F1-score ≥ 0.87 ([CONFLUENCE] PII Classifier — Evaluation Methodology).

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## Model Training

`⚠ stale`

Based on the available documentation, creating a new PII classifier specifically from a **Model Training** perspective involves the following process:

### Training Data Requirements

Per the [$[PII Classifier — Evaluation Methodology]$], training a new classifier requires a carefully balanced test set. For each language you want to support, you need **500 annotated documents** with the following PII category distribution:

- **Email addresses**: 100 instances per language
- **Phone numbers**: 80 instances per language
- **Postal addresses**: 60 instances per language
- **Names (first/last)**: 150 instances per language
- **Government IDs**: 40 instances per language
- **Credit card numbers**: 30 instances per language

Documents must come from at least **three distinct connector types**: structured data (CSV, JSON), unstructured text (PDF, plain text), and semi-structured logs (per [$[PII Classifier — Evaluation Methodology]$]).

### Language Support

The current hybrid pipeline (rule + ML) supports **EN/DE/FR** out of the box, as implemented in [$[DPLAT-005]$]. To add a new language, you would need to prepare a training set following the same distribution pattern (e.g., 100 email instances, 80 phone numbers, etc. for that language).

### Adjusting Sensitivity Levels

Sensitivity is controlled via the **confidence threshold**. The default is `0.8` (set via `CONFIDENCE_THRESHOLD` environment variable in the [$[pii-classifier-service]$] README). To adjust sensitivity:

- **Lower threshold** (e.g., 0.7) → more sensitive, catches more potential PII but increases false positives
- **Higher threshold** (e.g., 0.9) → less sensitive, only flags high-confidence matches

Workspace admins can also customize detection rules through the Compliance Vault interface, including enabling/disabling specific PII categories and creating allowlists for false-positive suppression (per [$[Compliance Vault — Module Overview]$]).

### Data Types That Can Be Tagged

The supported PII categories for tagging include (per [$[Compliance Vault — Module Overview]$]):

| Category | Detection Method |
|----------|-----------------|
| Email Address | Regex pattern |
| Phone Number | Regex pattern |
| National ID (e.g., German Personalausweis) | Format validation |
| Name (First/Last) | ML classifier |
| Address (Street, postal code) | Combined rules |
| IP Address | Regex pattern |

### Performance Targets for Training

When training a new classifier, you must meet these metrics (per [$[DPLAT-REQ-06]$]):
- **Precision** ≥ 0.95 on the validation set
- **Recall** ≥ 0.90 on the validation set
- Classification must complete within **200ms p99** per document (up to 100KB)

The hybrid pipeline (rule + ML) implemented in [$[DPLAT-005]$] achieved an **18.2% recall improvement** over the legacy rule-only approach, with **0.92 precision** (based on QA validation).

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Permissions Matrix

The **Permissions Matrix** for the PII Classifier is defined through the **Compliance Vault** module's role-based access control system, which governs who can create, configure, and override classifiers.

### How to Create a New Classifier

Creating a new classifier is not a direct action but is achieved through configuring PII detection rules within the Compliance Vault. According to [$[Compliance Vault — Module Overview]$], workspace admins can customize PII detection rules through the Compliance Vault interface. The process involves:

1. **Navigate to Settings → Compliance Vault** (per [$[Compliance Vault — Module Overview]$])
2. **Enable PII Auto-Tagging** for your workspaces
3. **Configure baseline PII detection rules** — this effectively creates the classifier configuration

The classifier itself is a **hybrid rule + ML pipeline** (per [$[PII Auto-Tagging — Policy and Behavior]$]) that runs at ingestion time. The configuration is defined via environment variables in the [$[pii-classifier-service]$] README, including `PII_PATTERNS_CONFIG_PATH` (path to regex patterns YAML/JSON file) and `CONFIDENCE_THRESHOLD` (default 0.8).

### Adjusting Sensitivity Levels

Sensitivity levels are adjusted through **confidence threshold** settings and **override mechanisms**, governed by the Permissions Matrix:

| Role | Sensitivity Adjustment Capability | Source |
|------|----------------------------------|--------|
| **Compliance Officer** | Can configure global PII rules, set confidence thresholds, approve tenant-level overrides | [$[Compliance Vault — Module Overview]$] |
| **Workspace Admin** | Can adjust confidence thresholds per tenant (requires compliance officer approval), create custom pattern rules, suppress specific PII types | [$[PII Auto-Tagging — Policy and Behavior]$] |
| **Data Steward** | Can review classifications and request corrections, but cannot adjust sensitivity levels directly | [$[Compliance Vault — Module Overview]$] |

The default confidence threshold is **0.75** for tagging (per [$[PII Auto-Tagging — Policy and Behavior]$]), and the service-level `CONFIDENCE_THRESHOLD` defaults to **0.8** (per [$[pii-classifier-service]$]). Workspace admins can lower this threshold for high-recall scenarios, but all overrides require compliance officer approval and are scoped to the requesting tenant (per [$[PII Auto-Tagging — Policy and Behavior]$]).

### What Data Types Can Be Tagged

The Permissions Matrix defines which data types are taggable based on the classifier's supported PII categories. The following data types can be tagged:

| PII Category | Detection Method | Example Values |
|-------------|-----------------|----------------|
| Email Address | Regex pattern | user@example.com |
| Phone Number | Regex pattern | +49 30 1234567 |
| National ID | Format validation | German Personalausweis |
| Name (First/Last) | ML classifier | John Doe |
| Address | Combined rules | Street, postal code |
| IP Address | Regex pattern | 192.168.1.100 |
| Government IDs | Format validation | Passport IDs |
| Credit Card Numbers | Regex pattern | 4111-1111-1111-1111 |

*Source: [$[Compliance Vault — Module Overview]$] and [$[PII Auto-Tagging — Policy and Behavior]$]*

**Important note on permissions**: The override mechanism (per [$[DPLAT-013]$]) allows workspace admins to review and override classifier decisions through a review interface showing confidence scores and suggested PII categories. All overrides are recorded in the audit log with timestamp, user identity, original classification, and new classification. This is the primary way the Permissions Matrix interacts with classifier configuration — ensuring that only authorized roles can modify detection behavior.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Classifier Creation

`⚠ stale`

To create a new classifier, you need to configure the **PII Classifier Service** as part of the Compliance Vault module's PII Auto-Tagging feature (F-B1). The classifier is not created via a single API call but rather through configuration and deployment of the microservice.

### How to Create a New Classifier

1. **Deploy the PII Classifier Service**: The service is implemented in the [$[pii-classifier-service]$] repository. You deploy it as a microservice with environment variables controlling its behavior. Key configuration includes setting `PII_PATTERNS_CONFIG_PATH` to point to your YAML/JSON file containing regex patterns for PII detection, and `CONFIDENCE_THRESHOLD` (default 0.8) to set the minimum confidence score for flagging PII (per [$[pii-classifier-service]$]).

2. **Configure Detection Rules**: The classifier uses a hybrid rule + ML pipeline that executes at ingestion time, replacing the legacy post-ingest design (per [$[DPLAT-005]$]). You define detection rules through:
   - **Regex patterns** for deterministic matching (e.g., email, phone, SSN)
   - **ML-based entity recognition** for probabilistic detection (e.g., names, addresses)
   
   Workspace admins can customize rules through the Compliance Vault interface: enable/disable specific PII categories, define custom regex patterns, set confidence thresholds, and create allowlists for false-positive suppression (per [$[Compliance Vault — Module Overview]$]).

3. **Activate the Classifier**: Once configured, the classifier runs automatically during data ingestion. When a connector ingests data, the PII Auto-Tagging engine scans column values, applies pattern-matching rules and ML classifiers, tags identified fields with standardized PII categories, and propagates tags to downstream reports (per [$[Compliance Vault — Module Overview]$]).

### Adjusting Sensitivity Levels

You can adjust sensitivity through two mechanisms:

- **Confidence Threshold**: Set the `CONFIDENCE_THRESHOLD` environment variable (0.0–1.0) to control how confident the classifier must be before flagging data as PII. Lower values increase sensitivity but may increase false positives (per [$[pii-classifier-service]$]).
- **Per-Category Configuration**: Workspace admins can enable/disable specific PII categories and override redaction defaults through the Compliance Vault interface (per [$[Compliance Vault — Module Overview]$]).

### Data Types That Can Be Tagged

The classifier supports tagging the following PII categories (per [$[Compliance Vault — Module Overview]$] and [$[PII Tagging — Initial Design (Legacy)]$]):

| Category | Detection Method |
|----------|-----------------|
| Email Address | Regex pattern |
| Phone Number | Regex pattern |
| National ID (e.g., German Personalausweis) | Format validation |
| Name (First/Last) | ML classifier |
| Address (Street, postal code) | Combined rules |
| IP Address | Regex pattern |
| SSN | Regex pattern |
| Credit Card Number | Regex pattern |

The system supports English, German, and French languages out of the box (per [$[DPLAT-005]$]), with the evaluation methodology requiring balanced representation across these languages in test sets (per [$[PII Classifier — Evaluation Methodology]$]).

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## Rule Editing

To create a new classifier within the **Rule Editing** subsection of the Classifier Configuration, you work through the **override mechanism** described in the PII Auto-Tagging policy [$[PII Auto-Tagging — Policy and Behavior]$]. The process involves:

1. **Access the Compliance Vault interface** – Navigate to the Compliance Vault settings where workspace admins can customize PII detection rules.
2. **Define custom regex patterns** – You can add tenant-specific regex patterns for proprietary data formats that are not covered by the default 20+ out-of-box PII patterns (per [$[DPLAT-EPIC-04]$]).
3. **Submit a compliance review request** – All new classifier rules require compliance officer approval. Workspace admins must submit a ticket referencing **DPLAT-013**, provide business justification and a data classification impact assessment, define the scope (specific connectors, data sources, or PII types), and specify a duration (temporary overrides expire after 90 days) (per [$[PII Auto-Tagging — Policy and Behavior]$]).

The system supports **custom pattern rules** as one of three override mechanisms, alongside detection suppression and confidence threshold adjustment.

## Adjusting Sensitivity Levels

To adjust sensitivity levels in the Rule Editing context, you modify the **confidence threshold** for ML-based detection:

- **Default threshold**: The system tags PII when confidence scores exceed **0.75** (per [$[PII Auto-Tagging — Policy and Behavior]$]).
- **Lowering the threshold**: Workspace admins can lower the 0.75 threshold for high-recall scenarios (e.g., when you want to catch more potential PII at the cost of more false positives).
- **Raising the threshold**: You can increase the threshold to reduce false positives, though the system's default `CONFIDENCE_THRESHOLD` environment variable is set to **0.8** (per [$[pii-classifier-service README]$]).

All threshold adjustments require compliance officer approval and are scoped to the requesting tenant. Override configurations are versioned and auditable.

## Data Types That Can Be Tagged

The classifier supports tagging the following PII categories through rule-based and ML-based detection (per [$[Compliance Vault — Module Overview]$] and [$[PII Classifier — Evaluation Methodology]$]):

| PII Category | Example Values | Detection Method |
|--------------|---------------|------------------|
| Email Address | user@example.com | Regex pattern |
| Phone Number | +49 30 1234567 | Regex pattern |
| National ID | German Personalausweis | Format validation |
| Name | First/Last name | ML classifier |
| Address | Street, postal code | Combined rules |
| IP Address | 192.168.1.100 | Regex pattern |
| Government IDs | Passport IDs | Regex pattern |
| Credit Card Numbers | 16-digit formats | Regex pattern |

The system supports **20+ out-of-box PII patterns** (per [$[DPLAT-EPIC-04]$]) and can be extended with custom patterns through the Rule Editing interface. Note that there is a known bug ([$[DPLAT-DEF-06]$]) where 4-digit Austrian postal codes are incorrectly flagged as PII, which is currently under investigation.

**Sources:**
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Access Control

`⚠ stale`

To create a new classifier with a focus on **Access Control**, you need to configure the PII Classifier Service as part of the Compliance Vault module. According to [$[pii-classifier-service — README]$], the service is a core component of the **MOD-B Compliance Vault** module implementing feature **F-B1 (PII Auto-Detection)**. The classifier analyzes data payloads to identify, classify, and tag Personally Identifiable Information (PII) such as email addresses, social security numbers, credit card numbers, and phone numbers.

The creation process involves:
1. **Deploying the microservice** — The PII Classifier Service runs as a standalone microservice. You configure it via environment variables, including `PII_PATTERNS_CONFIG_PATH` (path to regex patterns), `CONFIDENCE_THRESHOLD` (minimum confidence score to flag as PII, default 0.8), and `REDACTION_ENABLED` (whether to provide redacted output).
2. **Configuring the connector** — Using the [$[Connector Configuration API — Reference]$], workspace administrators with the `workspace-admin` role can create a connector instance via `POST /api/v1/connectors`. The request schema includes `pii_handling` settings such as `masking_enabled` and `excluded_fields` (e.g., SSN, credit_card). This ensures that PII detection and masking are applied at the connector level.
3. **Enabling hybrid rule + ML pipeline** — Per [$[DPLAT-005]$], the classifier now uses a hybrid rule + ML pipeline that executes **at ingestion time** (replacing the legacy post-ingest design). This means sensitive data is automatically identified and tagged immediately upon entry, reducing compliance risk.

For **Access Control** specifically, the classifier decisions feed into downstream governance policies. Workspace admins can review and override classifier decisions via a review interface, as described in [$[DPLAT-013]$]. All override actions are recorded in the audit log with timestamp, user identity, original classification, and new classification, ensuring full traceability for access control audits.

## Adjusting Sensitivity Levels

Sensitivity levels are configured through two mechanisms:

1. **Per-connector PII handling** — In the connector configuration API, you can set `pii_handling.masking_enabled` and specify `excluded_fields` to control which PII types are masked. This allows you to adjust sensitivity per data source.

2. **Confidence threshold** — The `CONFIDENCE_THRESHOLD` environment variable (default 0.8) controls the minimum confidence score required to flag data as PII. Lowering this value increases sensitivity (more items flagged) but may increase false positives. Raising it reduces sensitivity.

3. **Retention policy integration** — Per the legacy design in [$[PII Tagging — Initial Design (Legacy)]$], tagged PII automatically inherits retention rules based on sensitivity: High (SSN, CC) = 2 years, Medium (Email, Phone) = 5 years, Low (Zip code) = 7 years. Workspace admins can override redaction defaults for specific PII types.

4. **Custom regex patterns** — Workspace admins can add custom regex patterns via the UI (validated server-side) to adjust detection sensitivity for specific data types.

## Data Types That Can Be Tagged

The classifier supports tagging the following PII data types, as documented in the legacy design and confirmed by the evaluation methodology in [$[PII Classifier — Evaluation Methodology]$]:

| PII Type | Example Pattern | Default Redaction |
|----------|----------------|-------------------|
| SSN | `\b\d{3}-\d{2}-\d{4}\b` | Yes |
| Email | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | No |
| Phone (US) | `\(\d{3}\)\s*\d{3}-\d{4}` | No |
| Credit Card | `\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b` | Yes |
| US Zip Code | `\b\d{5}(-\d{4})?\b` | No |
| Postal Addresses | Pattern-based | No |
| Names (first/last) | Pattern-based | No |
| Government IDs | Pattern-based | No |

The evaluation methodology also specifies that test sets must include balanced representation across these categories, with specific instance counts per language (e.g., 100 email instances, 80 phone numbers, 60 postal addresses, 150 names, 40 government IDs, 30 credit card numbers per language).

**Important for Access Control**: The hybrid pipeline (per [$[DPLAT-005]$]) now supports **EN/DE/FR languages** out of the box, with ML-based entity recognition improving recall by 18.2% over the legacy rule-only approach while maintaining precision at 0.92. This means access control policies can be applied more accurately across multilingual tenants. Additionally, per [$[DPLAT-REQ-06]$], the classifier must maintain precision ≥ 0.95 and recall ≥ 0.90 on the EN/DE/FR validation set to minimize false positives that could block legitimate business data flows.

**Sources:**
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## Audit

To create a new PII classifier within the **Audit** context of the Compliance Vault module, you need to configure the **pii-classifier-service** microservice, which implements feature **F-B1 (PII Auto-Detection)**. According to [$[pii-classifier-service]$], the service analyzes data payloads to identify, classify, and tag PII patterns such as email addresses, social security numbers, credit card numbers, and phone numbers, feeding into the compliance pipeline for audit trail generation.

The primary configuration is done via environment variables. To set up a new classifier, you must define a path to your PII detection patterns using the `PII_PATTERNS_CONFIG_PATH` variable (default: `/app/config/pii_patterns.yaml`), which contains regex patterns for PII detection. You can also set the `CONFIDENCE_THRESHOLD` (default: `0.8`) to control the minimum confidence score required to flag data as PII. For audit-specific purposes, ensure `REDACTION_ENABLED` is set appropriately if you need redacted output alongside classification.

## Adjusting Sensitivity Levels

Sensitivity levels are adjusted through the **confidence threshold** and the **PII pattern configuration**. Per [$[pii-classifier-service]$], the `CONFIDENCE_THRESHOLD` environment variable (range 0.0–1.0) determines the minimum score to flag content as PII — lowering it increases sensitivity (more detections), raising it reduces false positives. Additionally, the hybrid classifier described in [$[Release Notes — v2.3]$] combines ML-based detection with deterministic regex fallback, where each classification includes a confidence score (0.0–1.0) for review workflows. For audit purposes, workspace admins can also override classifier decisions via the review interface (per [$[DPLAT-013]$]), with all overrides recorded in the audit log with timestamp, user identity, original classification, and new classification.

## Data Types That Can Be Tagged

The classifier supports tagging multiple PII data types. According to the [$[PII Classifier — Evaluation Methodology]$], the evaluation test set includes balanced representation across these categories:

- **Email addresses** (100 instances per language)
- **Phone numbers** (80 instances per language)
- **Postal addresses** (60 instances per language)
- **Names (first/last)** (150 instances per language)
- **Government IDs** (40 instances per language)
- **Credit card numbers** (30 instances per language)

The hybrid classifier (per [$[DPLAT-005]$]) supports English, German, and French out of the box, with ML-based detection identifying patterns that regex alone cannot capture (e.g., names, addresses, social context). For audit compliance, all tagged data is automatically logged in the audit trail, and the [$[Connector Configuration API — Reference]$] notes that all configuration changes are recorded in the audit log with timestamp, actor, and diff, ensuring full traceability for compliance officers.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [Release Notes — v2.3 (April 2026)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/fc4e516f49c5)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## Validation & Testing

To create a new classifier for the PII Auto-Tagging feature (F-B1) within the **Validation & Testing** context, you need to follow the evaluation methodology defined in [$[PII Classifier — Evaluation Methodology]$]. The process involves several key steps:

### 1. Build the Classifier Configuration

The classifier uses a **hybrid rule + ML pipeline** that executes at ingestion time, as documented in [$[PII Auto-Tagging — Policy and Behavior]$]. You configure it by:
- Setting environment variables in the [$[pii-classifier-service]$] (e.g., `PII_PATTERNS_CONFIG_PATH` for regex patterns, `CONFIDENCE_THRESHOLD` defaulting to 0.8)
- Defining regex patterns for deterministic detection (email, phone, SSN, etc.)
- Training ML models for context-aware entity recognition (names, addresses)

### 2. Prepare the Validation Test Set

Per the evaluation methodology, your test set must include:
- **500 annotated documents per language** (English: 200, Spanish: 100, French: 75, German: 75, Portuguese: 50)
- **Balanced PII categories**: 100 emails, 80 phone numbers, 60 postal addresses, 150 names, 40 government IDs, 30 credit card numbers per language
- **At least 3 connector types**: structured (CSV/JSON), unstructured (PDF/text), and semi-structured logs

### 3. Adjust Sensitivity Levels

You can adjust sensitivity through two mechanisms:
- **Confidence threshold**: The `CONFIDENCE_THRESHOLD` environment variable (default 0.8) controls the minimum score to flag as PII. Lowering it increases recall but may increase false positives.
- **Per-tenant overrides**: Workspace admins can adjust the 0.75 tagging threshold for high-recall scenarios, as described in [$[PII Auto-Tagging — Policy and Behavior]$]. All overrides require compliance officer approval and are logged.

### 4. Data Types That Can Be Tagged

The classifier supports tagging the following data types (per [$[Compliance Vault — Module Overview]$]):
- **Email Address** (regex)
- **Phone Number** (regex)
- **National ID** (format validation)
- **Name** (ML classifier)
- **Address** (combined rules)
- **IP Address** (regex)
- **Credit Card Numbers** (regex)
- **Government IDs** (format validation)

### 5. Validation & Testing Process

To validate your classifier:
1. **Run the test suite**: Execute `pytest tests/ -v` from the service's local development setup
2. **Measure primary metrics**: Precision ≥ 0.90, Recall ≥ 0.85, F1-Score ≥ 0.87 per category
3. **Conduct human review**: Reviewers must complete PII Annotation Training (DPLAT-005) and achieve ≥0.80 inter-annotator agreement
4. **Perform A/B testing**: Follow the phased rollout (Canary → Alpha → Beta → Full) with monitoring for F1 regression, false positive complaints, and latency increases
5. **Meet the requirement from [$[DPLAT-REQ-06]$]**: Precision ≥ 0.95 and Recall ≥ 0.90 on the EN/DE/FR validation dataset (minimum 10,000 labeled records per language)

**Note**: The evaluation methodology specifies that test documents must originate from at least three distinct connector types to ensure cross-source generalization. All evaluation artifacts are retained for 7 years per compliance requirements.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)

## Test Sets

To create a new classifier focused on the **Test Sets** aspect, you need to follow the evaluation methodology defined in the [$[PII Classifier — Evaluation Methodology]$]. The process involves constructing a balanced test set that meets specific composition requirements:

### Test Set Composition Requirements

1. **Language Distribution**: Your test set must include exactly **500 annotated documents** per language cohort, distributed as follows:
   - English: 200 documents (100–50,000 characters each)
   - Spanish: 100 documents
   - French: 75 documents
   - German: 75 documents
   - Portuguese: 50 documents

2. **PII Category Balance**: Each test set must contain balanced instances across target PII categories per language:
   - Email addresses: 100 instances
   - Phone numbers: 80 instances
   - Postal addresses: 60 instances
   - Names (first/last): 150 instances
   - Government IDs: 40 instances
   - Credit card numbers: 30 instances

3. **Source Diversity**: Test documents must originate from at least **three distinct connector types**:
   - Structured data (CSV, JSON, database exports)
   - Unstructured text (PDF, plain text, email bodies)
   - Semi-structured logs

### Adjusting Sensitivity Levels

You can adjust sensitivity levels through the **confidence threshold** configuration. According to the [$[PII Auto-Tagging — Policy and Behavior]$], the default tagging threshold is **0.75** (confidence score 0.0–1.0). To adjust sensitivity:

- **Lower the threshold** (e.g., to 0.6) for high-recall scenarios where you want to catch more potential PII, accepting more false positives
- **Raise the threshold** (e.g., to 0.9) for high-precision scenarios where you want to minimize false positives

Workspace admins can override the default threshold per tenant through the Compliance Vault interface, but all overrides require compliance officer approval and are scoped to the requesting tenant (per [$[PII Auto-Tagging — Policy and Behavior]$]).

### Data Types That Can Be Tagged

The classifier supports tagging the following PII data types, as documented in the [$[Compliance Vault — Module Overview]$] and [$[PII Auto-Tagging — Policy and Behavior]$]:

| PII Category | Detection Method |
|-------------|------------------|
| Email Address | Regex pattern |
| Phone Number | Regex pattern |
| National ID (e.g., German Personalausweis) | Format validation |
| Name (First/Last) | ML classifier |
| Address (Street, postal code) | Combined rules |
| IP Address | Regex pattern |
| SSN | Regex pattern |
| Credit Card Numbers | Regex pattern |
| Government IDs | Format validation |

The hybrid detection engine combines **rule-based detection** (regex patterns for known formats) with **ML classification** (context-aware models for names, addresses, and other sensitive entities). Each detection receives a confidence score, and tagging occurs above the configured threshold (default 0.75).

**Important**: For test set creation, ensure your test documents include all these PII categories in the required instance counts per language to properly evaluate classifier performance across all supported data types.

**Sources:**
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## Accuracy Metrics

`⚠ conflict`

### Creating a New Classifier

To create a new classifier in the PII Auto-Tagging system, you configure the detection engine through the Compliance Vault interface. The classifier uses a **hybrid rule + ML pipeline** that executes at ingestion time, as documented in [$[DPLAT-005]$]. The system supports configurable pattern matching rules, sensitivity level assignment, and optional redaction preview capabilities.

The key configuration parameter affecting accuracy is the **`CONFIDENCE_THRESHOLD`** environment variable, which defaults to **0.8** (on a 0.0–1.0 scale) per the [$[pii-classifier-service]$] README. However, the auto-tagging policy in [$[PII Auto-Tagging — Policy and Behavior]$] states that tagging occurs above a **0.75 threshold**. This discrepancy means you should verify which threshold applies to your deployment.

### Adjusting Sensitivity Levels

You can adjust sensitivity levels by modifying the confidence threshold. The system supports:

- **Lowering the threshold** (e.g., to 0.75) for high-recall scenarios where catching more potential PII is prioritized over precision
- **Raising the threshold** (e.g., to 0.95) for high-precision scenarios where false positives must be minimized

Per-tenant overrides are available through the tenant configuration API, but require compliance officer approval and are scoped to the requesting tenant (as described in [$[PII Auto-Tagging — Policy and Behavior]$]).

### Data Types That Can Be Tagged

The classifier supports tagging the following PII categories, as listed in [$[Compliance Vault — Module Overview]$]:

| Category | Example | Detection Method |
|----------|---------|-----------------|
| Email Address | user@example.com | Regex pattern |
| Phone Number | +49 30 1234567 | Regex pattern |
| National ID | German Personalausweis | Format validation |
| Name | First/Last name | ML classifier |
| Address | Street, postal code | Combined rules |
| IP Address | 192.168.1.100 | Regex pattern |

### Accuracy Metrics Requirements

For the "Accuracy Metrics" subsection specifically, the evaluation methodology in [$[PII Classifier — Evaluation Methodology]$] defines the following **target metrics**:

| Metric | Target |
|--------|--------|
| Precision | ≥ 0.90 |
| Recall | ≥ 0.85 |
| F1-Score | ≥ 0.87 |

Additionally, the non-functional requirement [$[DPLAT-REQ-06]$] mandates **Precision ≥ 0.95** and **Recall ≥ 0.90** on the EN/DE/FR validation dataset (minimum 10,000 labeled records per language). This is a stricter requirement than the evaluation methodology baseline.

The evaluation test set must include **500 annotated documents per language** (English, Spanish, French, German, Portuguese) with balanced PII category representation (e.g., 100 email instances, 80 phone numbers, 150 names per language). Test documents must originate from at least **three distinct connector types** (structured data, unstructured text, semi-structured logs).

**Important note**: The evaluation methodology and DPLAT-REQ-06 have slightly different precision targets (0.90 vs. 0.95). The stricter requirement (0.95) from the non-functional requirement should be considered the binding target for production deployments.

**Sources:**
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-020] Salesforce — usage metrics dashboard by object type](https://demo-jira.local/browse/DPLAT-020)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-025] SAP — field type mapping for German locale (DECIMAL/NUMC/CHAR)](https://demo-jira.local/browse/DPLAT-025)

## Sandbox Testing

# Classifier Configuration for Sandbox Testing

## Creating a New Classifier

To create a new PII classifier for sandbox testing, you need to configure the **pii-classifier-service** microservice. According to [GITHUB] pii-classifier-service README, the service is configured through environment variables. For sandbox testing, you would:

1. **Set up the configuration file**: Create or modify the YAML/JSON file at the path specified by `PII_PATTERNS_CONFIG_PATH` (default: `/app/config/pii_patterns.yaml`). This file contains regex patterns for PII detection.

2. **Configure confidence thresholds**: Set `CONFIDENCE_THRESHOLD` (default: 0.8) to control the minimum confidence score required to flag content as PII. For sandbox testing, you may want to lower this to test edge cases.

3. **Enable redaction preview**: Set `REDACTION_ENABLED` to `true` to see redacted output alongside classification results, which is useful for sandbox validation.

4. **Run the service locally**: Use the development commands from the README:
   ```bash
   pip install -r requirements.txt
   export LOG_LEVEL=DEBUG
   uvicorn main:app --reload --port 8001
   ```

5. **Run tests**: Execute `pytest tests/ -v` to validate your configuration against the test suite.

## Adjusting Sensitivity Levels

Sensitivity levels are controlled through the **confidence threshold** mechanism. Per [CONFLUENCE] PII Auto-Tagging — Policy and Behavior:

- The default detection threshold is **0.75** for the hybrid rule+ML pipeline
- The `CONFIDENCE_THRESHOLD` environment variable (default: 0.8) provides an additional layer of control
- For sandbox testing, you can **lower the threshold** to test high-recall scenarios (catching more potential PII) or **raise it** to test high-precision scenarios (reducing false positives)

Workspace admins can also adjust sensitivity through the Compliance Vault interface by:
- Enabling/disabling specific PII categories
- Creating custom regex patterns for organization-specific identifiers
- Setting confidence thresholds for ML-based detection
- Creating allowlists for false-positive suppression

## Data Types That Can Be Tagged

Based on [CONFLUENCE] Compliance Vault — Module Overview and [CONFLUENCE] PII Classifier — Evaluation Methodology, the following data types are supported for tagging:

| Category | Example Values | Detection Method |
|----------|---------------|------------------|
| Email Address | user@example.com | Regex pattern |
| Phone Number | +49 30 1234567 | Regex pattern |
| National ID | German Personalausweis | Format validation |
| Name | First/Last name | ML classifier |
| Address | Street, postal code | Combined rules |
| IP Address | 192.168.1.100 | Regex pattern |
| Credit Card Numbers | 4111-1111-1111-1111 | Regex pattern |
| Government IDs | Various formats | Format validation |

For sandbox testing, the evaluation methodology recommends using test sets with balanced representation across these categories—for example, 100 email instances, 80 phone numbers, 60 postal addresses, 150 names, 40 government IDs, and 30 credit card numbers per language.

## Sandbox Testing Specifics

For sandbox testing, the [CONFLUENCE] PII Classifier — Evaluation Methodology provides a structured approach:

1. **Use diverse test data**: Include documents from at least three connector types (structured data like CSV/JSON, unstructured text like PDF/email, and semi-structured logs)
2. **Test across languages**: The classifier supports EN, DE, and FR with specific test set compositions (200 English documents, 100 Spanish, 75 French, 75 German, 50 Portuguese)
3. **Measure key metrics**: Track precision (target ≥ 0.90), recall (target ≥ 0.85), and F1-score (target ≥ 0.87) per PII category
4. **Use the A/B testing framework**: For model updates, follow the four-stage rollout (Canary → Alpha → Beta → Full) with specific exit criteria and rollback triggers

The sandbox environment allows you to validate classifier behavior before deploying to production, ensuring that PII detection meets your organization's compliance requirements without disrupting live data flows.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [Connector Configuration API — Reference](https://demo-confluence.local/wiki/spaces/DPLAT/pages/84b031dace84)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-021] SAP — table whitelist configuration UI](https://demo-jira.local/browse/DPLAT-021)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [Connector Framework — Architecture Deep-Dive](https://demo-confluence.local/wiki/spaces/DPLAT/pages/478d2ab49b1e)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-001] Connector Framework — configuration schema and validation layer](https://demo-jira.local/browse/DPLAT-001)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)

## Result Review

`⚠ conflict`

Based on the available documentation, the PII Classifier is **not created from scratch by end users**. Instead, it is a pre-built microservice (the **pii-classifier-service**) that is configured and deployed as part of the Compliance Vault module. The "creation" process involves configuring the existing classifier through environment variables and policy settings.

### How to Configure a New Classifier Instance

To set up a new classifier instance, you configure the following parameters in the service's environment ([GITHUB] pii-classifier-service README):

| Parameter | Purpose |
|-----------|---------|
| `PII_PATTERNS_CONFIG_PATH` | Path to YAML/JSON file with regex patterns for PII detection |
| `CONFIDENCE_THRESHOLD` | Minimum confidence score (0.0–1.0) to flag as PII (default: 0.8) |
| `REDACTION_ENABLED` | Whether to provide redacted output alongside classification |

The classifier uses a **hybrid rule + ML pipeline** that executes at ingestion time ([CONFLUENCE] PII Auto-Tagging — Policy and Behavior). It combines deterministic regex patterns with ML-based entity recognition.

### Adjusting Sensitivity Levels

Sensitivity is controlled through the **confidence threshold**:

- **Default threshold**: 0.8 (from service configuration) or 0.75 (from policy documentation — note the slight discrepancy between sources)
- **Lowering the threshold** increases recall (catches more potential PII) but may increase false positives
- **Raising the threshold** increases precision but may miss some PII

Workspace admins can adjust the confidence threshold per tenant through the **override mechanism** ([CONFLUENCE] PII Auto-Tagging — Policy and Behavior). To request a threshold change:
1. Submit a ticket referencing **DPLAT-013**
2. Provide business justification and data classification impact assessment
3. Define scope (specific connectors, data sources, or PII types)
4. Specify duration (temporary overrides expire after 90 days)

All overrides require **compliance officer approval**.

### Data Types That Can Be Tagged

The classifier supports tagging the following PII categories ([CONFLUENCE] PII Classifier — Evaluation Methodology):

| PII Category | Description |
|--------------|-------------|
| **Email addresses** | Full coverage for supported languages |
| **Phone numbers** | International formats |
| **Postal addresses** | Full street addresses (not postal codes alone) |
| **Names (first/last)** | Person names |
| **Government IDs** | Passport IDs, SSNs, Personalausweisnummer |
| **Credit card numbers** | Standard credit card formats |

**Important note on Result Review**: The classifier currently has a known bug ([JIRA] DPLAT-DEF-06) where **4-digit Austrian-style postal codes** (e.g., "1010", "6020") are incorrectly flagged as PII with 0.92 confidence. This is a false positive — postal codes alone are geographic identifiers, not PII. The workaround is to manually exclude postal code fields from scanning, or pre-process data to replace 4-digit codes with placeholders. This issue is **Open** and awaiting a fix.

### Result Review Workflow

After classification, workspace admins can review results through the **review interface** implemented in [$[DPLAT-013]$] ([JIRA] DPLAT-013). This interface shows:
- Field name and source connector
- Current PII tag and confidence score
- Override dropdown to change classification

For false-positive management, the **False-Positive Review Queue** ([JIRA] DPLAT-032) provides bulk approve/reject actions, with all changes logged in the audit trail.

**Sources:**
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-041] Health Monitor — surface PII classifier latency metrics](https://demo-jira.local/browse/DPLAT-041)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
