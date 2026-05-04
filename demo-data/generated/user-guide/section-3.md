# 3  Working with PII tagging

_Feature: `F-B1` · Audience: end-user, workspace-admin_

> Managing sensitive data identification

## Understanding PII Tags

### How PII Auto-Tagging Works

PII auto-tagging in the Compliance Vault module uses a **hybrid detection model** that combines rule-based pattern matching with machine learning classification (per [$[PII Auto-Tagging — Policy and Behavior]$]). The detection engine operates **synchronously during data ingestion**:

1. **Rule-based detection**: Regex patterns identify known PII formats such as email addresses, Social Security numbers, phone numbers, and passport IDs
2. **ML classification**: Context-aware models detect names, addresses, and other sensitive entities
3. **Confidence scoring**: Each detection receives a score from 0.0 to 1.0; tagging occurs above a **0.75 threshold** (configurable per tenant)

The system supports **English, German, and French** at launch, with unsupported languages falling back to English models at reduced confidence thresholds. Each classification event generates an audit log entry with the matched pattern (for rule-based) or model version and feature importance summary (for ML-based detections).

**Important note**: The current implementation has a known defect ([$[DPLAT-DEF-07]$]) where CSV imports only scan the first 100 rows, potentially missing PII in larger files. This is an open bug being addressed.

### How to Review Tagged Data

Workspace admins can review auto-classified fields through a **dedicated review interface** (implemented in [$[DPLAT-013]$]). The interface displays:
- Field name and source connector
- Current PII tag and confidence score
- An override dropdown for reclassification

Additionally, compliance officers have access to a **False-Positive Review Queue** ([$[DPLAT-032]$]) that lists flagged items with their source field, detected PII type, and confidence score. This queue supports **bulk approve/reject actions** — selecting multiple items and confirming them as true PII or rejecting them as false positives in a single operation.

### Can I Override PII Tags?

**Yes.** Workspace admins can override auto-tagging decisions through several mechanisms:

1. **Direct override**: Select an alternative PII category from the supported taxonomy via the review interface ([$[DPLAT-013]$])
2. **Detection suppression**: Exclude specific PII types from auto-tagging for approved use cases
3. **Confidence threshold adjustment**: Lower the 0.75 threshold for high-recall scenarios
4. **Custom pattern rules**: Add tenant-specific regex patterns for proprietary data formats

All overrides require **compliance officer approval** and are scoped to the requesting tenant. Override configurations are versioned and auditable. Every override action is automatically captured in the audit log with an immutable SHA-256 hash chain linking to the previous entry, recording the user ID, timestamp, original classification, new classification, and data record identifier ([$[DPLAT-042]$]).

To request an override, workspace admins must submit a ticket referencing DPLAT-013 with business justification, data classification impact assessment, scope definition, and duration (temporary overrides expire after 90 days).

**Sources:**
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)

## Automated Tagging Logic

### How PII Auto-Tagging Works

The PII Auto-Tagging feature uses a **hybrid detection model** that combines deterministic rule-based pattern matching with machine learning classification [$[PII Auto-Tagging — Policy and Behavior]$]. The detection engine operates as follows:

1. **Rule-based detection**: Regex patterns identify known PII formats such as email addresses, Social Security numbers, phone numbers, and passport IDs.
2. **ML classification**: Context-aware models identify names, addresses, and other sensitive entities that may not follow fixed patterns.
3. **Confidence scoring**: Each detection receives a confidence score between 0.0 and 1.0. Tagging occurs only when the score exceeds a **0.75 threshold** (per the policy document) or **0.8** (per the PII Classifier Service configuration) [$[PII Auto-Tagging — Policy and Behavior]$][$[pii-classifier-service — README]$].

The classification happens **synchronously during data ingestion** — content passes through the detection engine immediately after extraction, before any downstream processing. This ensures PII is identified before it enters analytics pipelines [$[PII Auto-Tagging — Policy and Behavior]$].

The detection engine supports **English, German, and French** at launch. Data in unsupported languages falls back to English models with reduced confidence thresholds [$[PII Auto-Tagging — Policy and Behavior]$].

**Note**: A known bug ([$[DPLAT-DEF-07]$]) currently limits CSV scanning to only the first 100 rows, meaning PII in rows 101+ may go undetected. This is under investigation.

### How to Review Tagged Data

Workspace admins can review auto-classified fields through a **dedicated review interface** that displays each field with its source connector, current PII tag, and confidence score [$[DPLAT-013]$]. The interface is sortable and includes an override dropdown for each entry.

Additionally, compliance officers have access to a **False-Positive Review Queue** ([$[DPLAT-032]$]) that lists items flagged as potential PII with their source field, detected PII type, and confidence score. This queue supports **bulk approve/reject actions** — officers can select multiple items and confirm them as true PII or reject them as false positives in a single action. All actions are recorded in the audit log.

### Can I Override PII Tags?

**Yes.** Workspace admins can override auto-tagging decisions through several mechanisms [$[PII Auto-Tagging — Policy and Behavior]$]:

1. **Direct override**: In the review interface, admins can select an alternative PII category from the supported taxonomy for any auto-classified field [$[DPLAT-013]$].
2. **Detection suppression**: Exclude specific PII types from auto-tagging for approved use cases.
3. **Confidence threshold adjustment**: Lower the 0.75 threshold for high-recall scenarios.
4. **Custom pattern rules**: Add tenant-specific regex patterns for proprietary data formats.

All overrides require **compliance officer approval** and are scoped to the requesting tenant. Override configurations are versioned and auditable. To request an override, workspace admins must submit a ticket referencing [$[DPLAT-013]$] with business justification and scope definition. Temporary overrides expire after 90 days [$[PII Auto-Tagging — Policy and Behavior]$].

Every override action is automatically captured in the **audit log** within 500ms, including the user ID, timestamp, original classification, new classification, and data record identifier. The audit log uses SHA-256 hash chaining to prevent retroactive tampering [$[DPLAT-042]$].

**Sources:**
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)

## Manual Review Process

### How PII Auto-Tagging Works

The PII Auto-Tagging feature (feature F-B1) automatically identifies and classifies personally identifiable information within data ingested through DPLAT connectors. According to [$[PII Auto-Tagging — Policy and Behavior]$], the detection engine uses a **hybrid rule+ML approach**: deterministic regex patterns for known PII formats (email, SSN, phone numbers, passport IDs) combined with context-aware machine learning classification for names, addresses, and other sensitive entities. Each detection receives a confidence score from 0.0 to 1.0, with tagging occurring above a **0.75 threshold** (per the current policy) or **0.8 threshold** (per the pii-classifier-service configuration). Classification happens **synchronously during ingestion** — content passes through the detection engine, gets tagged with metadata (type, confidence, position), and proceeds to storage with classification preserved, while an audit log entry is created for each event.

### How to Review Tagged Data

The manual review process is implemented through two dedicated Jira stories:

1. **Review Interface for Workspace-Admins** ([$[DPLAT-013]$]): Workspace-admins can access a review interface showing all auto-classified fields with their confidence scores and suggested PII categories. The interface features a sortable table displaying field name, source connector, current PII tag, confidence score, and an override dropdown. This allows admins to review and correct any classifier decisions.

2. **False-Positive Review Queue for Compliance Officers** ([$[DPLAT-032]$]): Compliance officers have a dedicated queue showing flagged items with their source field, detected PII type, and confidence score. This queue supports **bulk approve/reject actions** — officers can select multiple items using checkboxes and either:
   - **Bulk Approve**: Confirms items as true PII, retaining the PII tag and continuing retention policy application.
   - **Bulk Reject**: Removes the PII tag from the data and clears items from the review queue.

All review actions are recorded in the audit log with timestamp, user identity, original classification, and new classification ([$[DPLAT-042]$]).

### Can I Override PII Tags?

**Yes.** Workspace-admins can override auto-tagging behavior through multiple mechanisms:

- **Per-field overrides**: Via the review interface, admins can select an alternative PII category from the supported taxonomy for any auto-classified field ([$[DPLAT-013]$]).
- **Tenant-level configuration overrides**: Per the [$[PII Auto-Tagging — Policy and Behavior]$], admins can:
  - Suppress detection for specific PII types (with compliance officer approval)
  - Adjust the confidence threshold (lowering the 0.75 threshold for high-recall scenarios)
  - Add custom regex patterns for proprietary data formats
- **Override requests** require a ticket referencing [$[DPLAT-013]$] with business justification, scope definition (specific connectors, data sources, or PII types), and duration (temporary overrides expire after 90 days).

All overrides are **versioned and auditable** — the audit log captures every override with immutable SHA-256 hash chaining to prevent tampering ([$[DPLAT-042]$]). Overridden classifications are also used as training feedback to improve future automated classifications.

**Important caveat**: Known bugs may affect review accuracy. [$[DPLAT-DEF-07]$] reports that CSV imports only scan the first 100 rows, potentially missing PII in larger files. [$[DPLAT-DEF-17]$] documents that the Italian fiscal-code regex produces false positives on valid order IDs. These issues should be considered during manual review.

**Sources:**
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)

## Data Privacy Rules

### How PII Auto-Tagging Works

PII auto-tagging in the Compliance Vault module uses a **hybrid detection model** that combines deterministic pattern matching with machine learning classification (per [$[PII Auto-Tagging — Policy and Behavior]$]). The detection engine processes data **synchronously during ingestion** — as soon as a connector extracts raw data, it passes through the PII detection engine where entities are identified, classified with metadata (type, confidence score, position), and tagged before storage. Each classification event generates an audit log entry.

The system supports three languages at launch: English (full coverage for US/UK/international), German (optimized for DACH region), and French (coverage for France and international French). Data in unsupported languages falls back to English models with reduced confidence thresholds.

**Data residency controls** are a core privacy feature: PII-tagged data never leaves its designated residency region without explicit consent and appropriate safeguards (GDPR Art. 44 compliance). EU citizen data defaults to EU region storage, German citizen data to DE region (with additional BDSG protections), and US citizen data to US region (with state-specific rules). Connectors automatically route data to the correct regional storage based on detected PII origin.

The **default retention period** for PII-tagged data is **30 days** (platform-wide), after which data is automatically anonymized or deleted. However, per-tenant retention overrides are available — workspace admins can set custom retention periods (1–365 days) via the Compliance Vault UI, with a new default of **60 days** being introduced for PII-tagged data in connector caches (per [$[DPLAT-006]$]).

### How to Review Tagged Data

Workspace admins can review auto-classified fields through a **dedicated review interface** (implemented in [$[DPLAT-013]$]). This interface displays all auto-classified fields in a sortable table showing:
- Field name and source connector
- Current PII tag and confidence score
- An override dropdown for reclassification

Additionally, compliance officers have access to a **False-Positive Review Queue** (per [$[DPLAT-032]$]) that lists flagged items with their source field, detected PII type, and confidence score. This queue supports **bulk approve/reject actions** — selecting multiple items and confirming them as true PII or rejecting them as false positives in a single action. All actions are recorded in the audit log.

### Can I Override PII Tags?

**Yes.** Workspace admins can override auto-tagging decisions through several mechanisms (per [$[PII Auto-Tagging — Policy and Behavior]$]):

1. **Direct reclassification**: In the review interface, admins can select an alternative PII category from the supported taxonomy for any auto-classified field.

2. **Detection suppression**: Exclude specific PII types from auto-tagging for approved use cases.

3. **Confidence threshold adjustment**: Lower the 0.75 default threshold for high-recall scenarios.

4. **Custom pattern rules**: Add tenant-specific regex patterns for proprietary data formats.

**All overrides require compliance officer approval** and are scoped to the requesting tenant. To request an override, workspace admins must submit a ticket referencing DPLAT-013 with business justification, data classification impact assessment, scope definition (specific connectors, data sources, or PII types), and duration (temporary overrides expire after 90 days).

**Every override action is automatically captured in the audit log** (per [$[DPLAT-042]$]) with immutable SHA-256 hash chaining, including the user ID, timestamp, original classification, new classification, data record identifier, and the workspace-admin's full name and email. This ensures a complete, tamper-evident record for regulatory compliance under GDPR and CCPA.

**Known limitation**: A bug ([$[DPLAT-DEF-07]$]) currently causes CSV imports to only scan the first 100 rows for PII detection, potentially missing PII in larger files. The workaround is to manually tag the column as PII before import or split large files into chunks.

**Sources:**
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)

## Verification

`⚠ conflict`

### How PII Auto-Tagging Works

PII auto-tagging uses a **hybrid detection model** combining rule-based pattern matching with machine learning classification [$[PII Auto-Tagging — Policy and Behavior]$]. The detection engine processes data **synchronously during ingestion** through the following flow:

1. The connector extracts raw data from the source
2. Content passes through the PII detection engine, which applies:
   - **Regex patterns** for known PII formats (email, SSN, phone numbers, passport IDs)
   - **ML classification** for context-aware identification of names, addresses, and other sensitive entities
3. Each detection receives a **confidence score (0.0–1.0)**, with tagging occurring above a **0.75 threshold** (per the policy) or **0.8 threshold** (per the classifier service configuration)
4. Tagged content proceeds to storage with classification preserved
5. An audit log entry is created for each classification event

The system supports **English, German, and French** at launch, with unsupported languages falling back to English models at reduced confidence thresholds [$[PII Auto-Tagging — Policy and Behavior]$].

### How to Review Tagged Data

Workspace admins can review auto-classified fields through a **dedicated review interface** [$[DPLAT-013]$]. This interface displays a sortable table showing:

- Field name
- Source connector
- Current PII tag
- Confidence score
- Override dropdown

Additionally, compliance officers have access to a **False-Positive Review Queue** [$[DPLAT-032]$] that lists flagged items with their source field, detected PII type, and confidence score. This queue supports **bulk approve/reject actions** — selecting multiple items and confirming them as true PII or rejecting them as false positives in a single action.

### Can I Override PII Tags?

**Yes.** Workspace admins can override classifier decisions through the review interface by selecting an alternative PII category from the supported taxonomy [$[DPLAT-013]$]. All override actions are:

- **Recorded in the audit log** with timestamp, user identity, original classification, and new classification
- **Applied to existing data** immediately
- **Used as training feedback** to improve future automated classifications

The audit log captures overrides with **immutable hash chaining** (SHA-256) linking each entry to the previous one, preventing retroactive tampering [$[DPLAT-042]$]. Compliance officers can filter the audit log by "override" action type and date range for reporting.

**Important caveat:** A known bug [$[DPLAT-DEF-07]$] causes CSV imports to only scan the first 100 rows for PII, potentially leaving rows 101+ untagged. This is under investigation. Additionally, the Italian fiscal-code regex may produce false positives on valid order IDs [$[DPLAT-DEF-17]$], requiring manual whitelisting of conflicting patterns.

**Sources:**
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-031] PII — nested JSON field traversal up to 5 levels deep](https://demo-jira.local/browse/DPLAT-031)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)

## Troubleshooting (common)

`⚠ conflict` `⚠ stale`

### How PII Auto-Tagging Works

PII auto-tagging uses a **hybrid detection model** combining rule-based regex patterns with machine learning classification, according to the [$[PII Auto-Tagging — Policy and Behavior]$] documentation. During ingestion, the detection engine scans data synchronously: it extracts raw content, runs it through the PII detector, assigns metadata tags (type, confidence score, position), and creates an audit log entry for each classification event. The default confidence threshold for tagging is **0.75** (per the policy doc) or **0.8** (per the [$[pii-classifier-service]$] README configuration — this discrepancy may cause inconsistent behavior). The system supports English, German, and French at launch, with unsupported languages falling back to English models at reduced confidence.

**Known issue:** The legacy design (2024) used a purely regex-based approach with a fixed confidence of 0.95 and only English support, but the current hybrid model supersedes this.

### How to Review Tagged Data

Workspace admins can review auto-classified fields through a **review interface** showing field name, source connector, current PII tag, and confidence score (per [$[DPLAT-013]$]). Compliance officers have a dedicated **False-Positive Review Queue** ([$[DPLAT-032]$]) that lists flagged items with source field, detected PII type, and confidence score, supporting **bulk approve/reject** actions. All review actions are recorded in the audit log with timestamps and user identity.

### Can I Override PII Tags?

**Yes.** Workspace admins can override classifier decisions via the review interface by selecting an alternative PII category from the supported taxonomy ([$[DPLAT-013]$]). Additionally, per-tenant overrides include:
- **Detection suppression** — exclude specific PII types
- **Confidence threshold adjustment** — lower the 0.75 threshold
- **Custom pattern rules** — add tenant-specific regex patterns

All overrides require **compliance officer approval** and are scoped to the requesting tenant. Override configurations are versioned, auditable, and temporary overrides expire after 90 days ([$[PII Auto-Tagging — Policy and Behavior]$]). Override actions are automatically captured in the audit log with SHA-256 hash chaining for tamper evidence ([$[DPLAT-042]$]).

### Common Troubleshooting Issues

1. **CSV imports only scan first 100 rows** ([$[DPLAT-DEF-07]$]): A hardcoded buffer size limit causes PII detection to skip rows 101+. **Workaround:** Split large CSVs into chunks of 100 rows or fewer, or manually tag the column as PII before import. This is a **high-severity bug** with compliance implications (GDPR/CCPA).

2. **Italian fiscal-code regex false positives** ([$[DPLAT-DEF-17]$]): Valid order IDs matching `ORD-YYYYMMDD-XXXXX` are incorrectly flagged as Italian fiscal codes, locking orders for manual review. **Workaround:** Whitelist the `ORD-YYYYMMDD-XXXXX` pattern in the PII exclusion list before scanning. This has caused 47+ false positives in production.

3. **Retention policy inconsistency** ([$[DPLAT-006]$]): The platform-wide default retention for PII-tagged data is documented as 30 days, but the actual observed default is 90 days. A new 60-day default is being introduced for PII-tagged data, but existing data retains its original schedule until expiration.

**Sources:**
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
