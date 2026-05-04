# 3.2  Reviewing and overriding classifier decisions

> Human-in-the-loop management of automated tags.

## Review Workflow

To manually correct a PII tag, workspace admins access the review interface in Compliance Vault, which displays all auto-classified fields with confidence scores. They select the field, choose the correct PII category from the taxonomy, and confirm the override. The system immediately applies the change to existing data and logs the action in the audit log with user identity, timestamp, original and new classification, and data record identifier. Compliance officers can audit overrides by filtering the Audit Log Export by 'override' action type and date range. The workflow ensures all manual corrections are tracked and used as training feedback to improve future classifications.

**Sources:**
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-REQ-07] PII data residency — classifier inference must run in tenant-region only](https://demo-jira.local/browse/DPLAT-REQ-07)

## Queue Management

To manually correct a PII tag, access the review interface (e.g., False-Positive Review Queue) in Queue Management, select the field, and choose an alternative PII category from the taxonomy. For bulk operations, use checkboxes to select items and then bulk Approve or Reject. All overrides are automatically logged in the audit log with user ID, timestamp, original and new classification, and data record identifier. To audit overrides, use the Audit Log Export filtered by 'override' action type and date range. The workflow for tag review involves reviewing flagged items, applying corrections or bulk actions, and relying on the audit trail for compliance.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)

## Decision Interface

To manually correct a PII tag in the Decision Interface, navigate to the review interface (sortable table with field name, source connector, current PII tag, and confidence score). Select the field and use the override dropdown to choose the correct PII category. Confirm the override; it is applied immediately and logged in the audit log. To audit classifier overrides, go to the Audit Log Export (F-B2) and filter by action type 'override' and date range. The workflow for tag review includes accessing the review interface, reviewing auto-classified fields, overriding as needed, and optionally using the False-Positive Review Queue for bulk approve/reject actions. All overrides are recorded with immutable audit trails.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)

## Bulk Actions

### How to Manually Correct a PII Tag (Bulk)

To manually correct PII tags in bulk, use the **False-Positive Review Queue** implemented in [$[DPLAT-032]$]. This queue provides a dedicated interface where you can:

1. **Navigate** to the False-Positive Review Queue in the Compliance Vault UI
2. **Select multiple items** using checkboxes — each item shows the source field, detected PII type, and confidence score
3. **Bulk Approve** — confirms flagged items as true PII, retaining the PII tag and applying the retention policy
4. **Bulk Reject** — removes the PII tag from selected items, clears them from the review queue, and logs the action

When you perform a bulk Reject, the system removes the PII tag from the data and creates an audit log entry. Bulk Approve marks items as reviewed and keeps them under the PII retention policy.

For historical data corrections, a **bulk re-classification job** is planned in [$[DPLAT-034]$] (status: To Do, target version v2.5). This will allow selecting a date range and re-running PII auto-tagging rules across all connector data sources, preserving original classifications in the audit log for before/after comparison.

### How to Audit Classifier Overrides

All override actions are automatically captured in the audit log per [$[DPLAT-042]$]. Each entry includes:

- **User ID** and workspace-admin's full name and email
- **Timestamp** of the override
- **Original classification** and **new classification**
- **Data record identifier** and specific data source (connector)
- **Immutable SHA-256 hash** chaining to the previous entry, preventing tampering

The compliance officer can filter the Audit Log Export by "override" action type and date range to retrieve all matching PII override entries. This satisfies GDPR and CCPA audit requirements.

### Workflow for Tag Review

The complete workflow for bulk tag review is:

1. **Auto-classification** occurs at ingestion — the PII detection engine tags data with type, confidence score, and position
2. **Review queue** surfaces flagged items with confidence scores for human evaluation
3. **Bulk selection** — compliance officer selects multiple items via checkboxes
4. **Decision** — bulk Approve (confirm as PII) or bulk Reject (mark as false positive)
5. **Audit logging** — every decision is recorded with immutable hash chaining within 500ms
6. **Tag update** — PII tags are applied or removed from the data immediately
7. **Training feedback** — overridden classifications are used to improve future automated detections (per [$[DPLAT-013]$])

This workflow is specifically designed for the **compliance-officer role** and streamlines validation of PII detection accuracy while maintaining a complete, tamper-evident audit trail.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)

## Tag History

To manually correct a PII tag, workspace admins use the review interface to override the classifier's decision by selecting a different PII category. All overrides are automatically logged in the audit log with user identity, timestamp, original and new classification, and data source. Compliance officers can audit these overrides by filtering the Audit Log Export by 'override' action type and date range. The tag review workflow includes a false-positive review queue where bulk approve/reject actions can be taken, with all actions recorded in the audit log using immutable hash chaining (SHA-256) to ensure tamper-evident records.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)

## Override Management

To manually correct a PII tag, workspace-admins use the review interface to select an alternative category; all overrides are logged. To audit overrides, compliance officers filter the audit log by 'override' action type. The tag review workflow involves a false-positive review queue where items can be bulk approved or rejected, with every action recorded in an immutable audit trail.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Manual Correction

To manually correct a PII tag, workspace admins use the **review interface** implemented in [$[DPLAT-013]$]. This interface displays a sortable table showing each auto-classified field with its source connector, current PII tag, and confidence score. From this table, you can override any classifier decision by selecting an alternative PII category from the supported taxonomy via a dropdown menu. Once you confirm the override, the new classification is applied to existing data immediately, and the change is recorded in the audit log.

The workflow for tag review follows these steps:
1. Navigate to the review interface in the Compliance Vault module
2. Review the list of auto-classified fields, noting confidence scores (tagging occurs above the 0.75 threshold per [$[PII Auto-Tagging — Policy and Behavior]$])
3. For any misclassified field, select the correct PII category from the taxonomy dropdown
4. Confirm the override — the system applies the correction and logs the action

For bulk corrections, the [$[DPLAT-032]$] feature provides a **false-positive review queue** where compliance officers can select multiple items using checkboxes and perform bulk **Approve** (confirm as true PII) or **Reject** (mark as false positive) actions. A bulk Reject removes the PII tag from the data and logs the action; a bulk Approve retains the tag and marks the items as reviewed.

## Auditing Classifier Overrides

All override actions are fully auditable. Per [$[DPLAT-013]$], each override is recorded in the audit log with:
- **Timestamp** of the override
- **User identity** (workspace admin or compliance officer)
- **Original classification** (the auto-tagged PII type)
- **New classification** (the manually selected category)

Additionally, per the [$[PII Auto-Tagging — Policy and Behavior]$], the audit log captures the detection method (rule-based or ML), including the matched regex pattern or model version and feature importance summary. Compliance officers can run reports on override history via the audit log export feature, as noted in the comments of [$[DPLAT-013]$].

## Practical Example: Correcting a False Positive

A concrete example of when manual correction is needed is the bug documented in [$[DPLAT-DEF-17]$], where the Italian fiscal-code regex mistakenly tags valid order IDs (format `ORD-YYYYMMDD-XXXXX`) as PII. In this case, a workspace admin would:
1. Open the review interface and locate the incorrectly tagged order ID
2. See the false positive with high confidence score
3. Use the override dropdown to remove the PII tag (or reclassify it as non-PII)
4. The system logs the override and removes the tag from the data

The workaround described in [$[DPLAT-DEF-17]$] — manually whitelisting the `ORD-YYYYMMDD-XXXXX` pattern in the PII exclusion list — can also be applied via the tenant-level override mechanisms described in the policy documentation, which require compliance officer approval and are scoped to the requesting tenant.

**Sources:**
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)

## Justification

To manually correct a PII tag, workspace-admins use the Compliance Vault review interface: select the misclassified field, choose the correct PII category from the taxonomy, and confirm the override. For bulk false-positive review, compliance-officers use the dedicated queue with checkboxes to approve or reject multiple items at once. To audit overrides, filter the Audit Log Export by action type 'override' and date range; each entry includes user ID, timestamp, original/new classification, and data source, with SHA-256 hash chaining for tamper-evidence. All overrides are automatically logged within 500ms and applied to existing data.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Re-classification

To manually correct a PII tag, workspace-admins use the review interface in Compliance Vault to override the classifier's decision by selecting an alternative PII category. For bulk corrections, compliance-officers use the False-Positive Review Queue to approve or reject multiple flagged items at once. All overrides are automatically logged in an immutable audit trail with user identity, timestamp, original and new classification, and data source. To audit overrides, use the Audit Log Export filtered by 'override' action type and date range. The workflow for tag review involves: (1) reviewing auto-classified fields with confidence scores, (2) overriding individual or bulk classifications, (3) audit logging of all changes, and (4) using overrides as training feedback. Be aware of known issues: false positives from regex patterns (e.g., Italian fiscal codes), false negatives from CSV row limits, and crashes on documents over 1MB.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Versioning

To manually correct a PII tag, access the review interface in Compliance Vault, select the misclassified field, and choose the correct PII category from the taxonomy. The override is immediately applied and logged. To audit overrides, filter the audit log by 'override' action type; each entry includes user identity, timestamps, original and new classifications, and an immutable hash. For tag review, use the false-positive review queue to bulk approve or reject flagged items. All actions are recorded for compliance.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)

## Audit & Compliance

### How to Manually Correct a PII Tag

As a workspace-admin, you can manually correct a PII tag through the review interface implemented in [$[DPLAT-013]$]. The interface presents a sortable table showing each auto-classified field with its name, source connector, current PII tag, and confidence score. To override a classification, you select an alternative PII category from the supported taxonomy via a dropdown menu. The override is applied immediately to existing data and also used as training feedback to improve future automated classifications (per [$[DPLAT-013]$] acceptance criteria 2 and 4).

For compliance officers handling false positives, a dedicated **False-Positive Review Queue** (implemented in [$[DPLAT-032]$]) allows you to review flagged items with their source field, detected PII type, and confidence score. You can select multiple items using checkboxes and perform **bulk Approve** (confirm as true PII) or **bulk Reject** (mark as false positive) actions. A bulk Reject removes the PII tag and clears the item from the queue; a bulk Approve retains the PII tag and continues the retention policy (per [$[DPLAT-032]$] acceptance criteria 2–4).

### How to Audit Classifier Overrides

All override actions are automatically captured in the audit log, as specified in [$[DPLAT-042]$]. Each audit log entry is created within **500ms** and contains:
- User ID and workspace-admin's full name and email
- Timestamp of the override
- Original classification and new classification
- Data record identifier and specific data source (connector) where the override occurred

The audit log uses **SHA-256 hash chaining** — each entry includes an immutable hash linking to the previous entry, preventing retroactive tampering (per [$[DPLAT-042]$] acceptance criteria 1–2). Compliance officers can filter the audit log export by "override" action type and date range to retrieve all matching PII override entries (acceptance criterion 3).

### Workflow for Tag Review (Audit & Compliance Focus)

The complete workflow for tag review from an audit and compliance perspective is:

1. **Detection**: The PII Auto-Tagging engine (hybrid rule+ML) classifies data during ingestion, assigning confidence scores (threshold 0.75 per [$[PII Auto-Tagging — Policy and Behavior]$]). Each classification event creates an audit log entry.

2. **Review**: Workspace-admins access the review interface to inspect auto-classified fields. Compliance officers use the False-Positive Review Queue for bulk validation.

3. **Override/Correction**: The admin selects a new PII category or rejects the classification. For bulk actions, compliance officers use approve/reject in the queue.

4. **Audit Logging**: Every override is automatically recorded with full details (user, timestamp, original/new values, data source) and hash-chained for tamper evidence.

5. **Retention Impact**: Overridden classifications affect retention policy application. The default retention for PII-tagged data is **30 days** (per [$[PII Auto-Tagging — Policy and Behavior]$]), though a per-tenant override to **60 days** is being implemented in [$[DPLAT-006]$]. All retention override actions are also logged.

6. **Training Feedback**: Overridden classifications are fed back to improve the ML model, reducing future false positives (per [$[DPLAT-013]$] acceptance criterion 4).

**Important compliance note**: Known bugs may affect review accuracy. The classifier currently only scans the first 100 rows of CSV imports ([$[DPLAT-DEF-07]$]), crashes on documents over 1MB ([$[DPLAT-DEF-16]$]), and mislabels Austrian 4-digit postal codes as PII ([$[DPLAT-DEF-06]$]) and Italian order IDs as fiscal codes ([$[DPLAT-DEF-17]$]). These issues should be considered when auditing override history, as they may generate false positives requiring manual correction.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)

## Review Logs

### How to Manually Correct a PII Tag

As a workspace-admin, you can manually correct a PII tag through the review interface implemented in [$[DPLAT-013]$]. The workflow is:

1. **Access the Review Interface**: Navigate to the Compliance Vault's PII Detection section, where you'll find a sortable table displaying all auto-classified fields. The table shows each field's name, source connector, current PII tag, and confidence score.

2. **Override the Classification**: Use the override dropdown next to any auto-classified field to select an alternative PII category from the supported taxonomy. This action immediately corrects the tag for the existing data.

3. **Confirmation**: The system applies the new classification to the data record and uses the override as training feedback to improve future automated classifications (per [$[DPLAT-013]$] acceptance criteria #4).

### How to Audit Classifier Overrides

All override actions are automatically captured in the audit log, as specified in [$[DPLAT-042]$]. Each audit log entry includes:

- **User identity**: The workspace-admin's full name and email
- **Timestamp**: When the override occurred
- **Original classification**: The PII tag assigned by the classifier
- **New classification**: The corrected PII tag selected by the admin
- **Data source**: The specific connector where the override happened
- **Data record identifier**: Which record was affected

The audit log uses **SHA-256 hash chaining** to link each entry to the previous one, preventing retroactive tampering (per [$[DPLAT-042]$] acceptance criteria #2). Compliance officers can filter the audit log export by "override" action type and date range to retrieve all matching entries.

### Workflow for Tag Review

The complete review workflow, based on the [$[PII Auto-Tagging — Policy and Behavior]$] document and [$[DPLAT-013]$], follows these steps:

1. **Automatic Classification**: During ingestion, the hybrid rule+ML pipeline tags detected PII with a confidence score (0.0–1.0). Tagging occurs above the 0.75 threshold (or the tenant-configured threshold).

2. **Review Queue**: All auto-classified fields appear in the workspace-admin's review interface, sorted by confidence score for easy prioritization of low-confidence detections.

3. **Manual Review**: The admin examines each flagged field, considering the classifier's suggested category and confidence score.

4. **Override Decision**: If the classifier made an error (e.g., flagging an Austrian postal code as PII as reported in [$[DPLAT-DEF-06]$], or misidentifying an order ID as an Italian fiscal code per [$[DPLAT-DEF-17]$]), the admin selects the correct category or removes the PII tag entirely.

5. **Audit Logging**: The system automatically records the override in the audit log within 500ms, with all required metadata.

6. **Feedback Loop**: The corrected classification feeds back into the ML model to improve future detections, reducing similar errors over time.

**Important note**: Overrides are scoped to the requesting tenant and require compliance officer approval for certain configuration changes (like detection suppression or confidence threshold adjustments), as documented in the [$[PII Auto-Tagging — Policy and Behavior]$] override mechanism section.

**Sources:**
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)

## Decision Tracking

To manually correct a PII tag, workspace-admins use the review interface to override classifications by selecting an alternative PII category. To audit overrides, compliance officers filter the audit log by 'override' action type. The tag review workflow involves reviewing auto-classified fields, using the false-positive queue for bulk actions, and all changes are logged with immutable audit trails.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## User Accountability

To manually correct a PII tag, workspace-admins access the review interface in Compliance Vault, select the misclassified field, and choose the correct PII category from the taxonomy. For bulk false-positive review, compliance-officers use the False-Positive Review Queue to approve or reject multiple items at once. All override actions are automatically captured in the audit log with immutable entries (user, timestamp, original/new classification, data source). To audit overrides, filter the Audit Log Export by action type 'override' and date range. The workflow ensures accurate classification while maintaining a tamper-evident trail for regulatory compliance.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Compliance Export

### How to Manually Correct a PII Tag

To manually correct a PII tag in the Compliance Export context, a workspace admin accesses the **review interface** provided by the PII Auto-Tagging feature (F-B1). According to [$[DPLAT-013]$], this interface displays all auto-classified fields with their confidence scores and suggested PII categories in a sortable table showing field name, source connector, current PII tag, and confidence score. The admin can then override any classifier decision by selecting an alternative PII category from the supported taxonomy (e.g., changing a mislabeled postal code from "Address" to "Not PII").

The override mechanism is per-tenant, as described in [$[PII Auto-Tagging — Policy and Behavior]$]. To request an override, workspace admins must submit a ticket referencing DPLAT-013, provide business justification and a data classification impact assessment, define the scope (specific connectors, data sources, or PII types), and specify a duration (temporary overrides expire after 90 days). All overrides require compliance officer approval and are scoped to the requesting tenant.

### How to Audit Classifier Overrides

All override actions are automatically captured in the **audit log** for compliance export purposes. Per [$[DPLAT-042]$], when a workspace admin overrides a PII classification, an audit log entry is created within 500ms containing:
- User ID and workspace admin's full name and email
- Timestamp of the override
- Original classification and new classification
- Data record identifier and specific data source (connector) where the override occurred
- An immutable SHA-256 hash linking to the previous entry, preventing retroactive tampering

Compliance officers can filter the Audit Log Export (F-B2) by "override" action type and date range to retrieve all matching PII override entries. The audit log also records the reviewer identity and certification level, per-document agreement score, and disputed items with resolution rationale, as specified in the [$[PII Classifier — Evaluation Methodology]$].

### Workflow for Tag Review

The tag review workflow for Compliance Export follows this process:

1. **Detection**: The PII Auto-Tagging engine scans ingested data at ingestion time using a hybrid rule+ML approach, assigning confidence scores (0.0–1.0) to each detection. Tagging occurs above the 0.75 confidence threshold.

2. **Review Interface**: Workspace admins access the review interface showing all auto-classified fields with their confidence scores. They can sort by field name, source connector, current PII tag, and confidence score.

3. **Override Decision**: The admin selects an alternative PII category from the supported taxonomy. This action is recorded in the audit log with full traceability.

4. **Compliance Officer Approval**: All overrides require compliance officer approval before taking effect. Override configurations are versioned and auditable.

5. **Application**: Overridden classifications are applied to existing data and used as training feedback to improve future automated classifications.

6. **Export**: Compliance officers can export audit logs in JSON, CSV, or PDF formats for regulatory reporting and forensic analysis.

**Sources:**
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Tagging — Initial Design (Legacy)](https://demo-confluence.local/wiki/spaces/DPLAT/pages/bcc441569ea0)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [Compliance Vault — Module Overview](https://demo-confluence.local/wiki/spaces/DPLAT/pages/19b49b5fe7af)
- 📋 [[DPLAT-REQ-06] PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set](https://demo-jira.local/browse/DPLAT-REQ-06)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)

## Feedback Loop

To manually correct a PII tag, workspace-admins use the Compliance Vault review interface to select a field and choose an alternative PII category. All overrides are automatically logged in the audit trail with immutable hash chaining. To audit overrides, compliance-officers can filter the Audit Log Export by 'override' action type and date range. The tag review workflow includes a dedicated False-Positive Review Queue where compliance-officers can bulk approve or reject flagged items. These actions update the PII tags and create audit log entries. Overrides also serve as training feedback for the classifier.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Model Training Input

To manually correct a PII tag for Model Training Input, workspace-admins use the review interface to override the classifier decision by selecting an alternative PII category. All overrides are automatically logged in the audit log with user identity, original and new classification, and timestamp. To audit overrides, compliance-officers can filter the Audit Log Export by 'override' action type and date range. The workflow for tag review includes: (1) accessing the review interface showing auto-classified fields with confidence scores, (2) overriding individual tags or using the false-positive review queue for bulk approve/reject, (3) overrides are applied to existing data and used as training feedback, and (4) training-set updates create versioned entries in the model registry with full audit trail.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)

## Error Analysis

To manually correct a PII tag, workspace-admins use the review interface in Compliance Vault to select an alternative PII category. To audit overrides, compliance officers filter the audit log by 'override' action type. The tag review workflow involves reviewing flagged items in the False-Positive Review Queue, then bulk approving or rejecting. All actions are logged immutably. Known false positives (e.g., Austrian postal codes, Italian fiscal-code regex) require manual correction. Be aware of risks: CSV scanning limited to 100 rows, and documents over 1MB cause crashes.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Accuracy Improvement

To manually correct a PII tag, workspace-admins use the review interface in Compliance Vault to override individual classifications by selecting an alternative PII category. For bulk false-positive review, compliance-officers use the False-Positive Review Queue to approve or reject flagged items in bulk. All overrides are automatically logged in the immutable audit trail, which can be filtered by action type and date range for auditing. The workflow ensures accurate classification while maintaining a complete, tamper-evident record of all manual changes.

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📋 [[DPLAT-033] PII — training-set update flow with versioned model registry](https://demo-jira.local/browse/DPLAT-033)

## Feedback Logs

### How to Manually Correct a PII Tag

To manually correct a PII tag, workspace admins use the **review interface** implemented in [$[DPLAT-013]$]. This interface displays a sortable table showing:

- Field name
- Source connector
- Current PII tag
- Confidence score
- Override dropdown

To correct a tag, you select an alternative PII category from the supported taxonomy via the override dropdown. Once submitted, the change is applied to existing data and recorded in the audit log. Additionally, the corrected classification is used as training feedback to improve future automated classifications (per [$[DPLAT-013]$] acceptance criteria).

For bulk corrections of false positives, compliance officers can use the **False-Positive Review Queue** from [$[DPLAT-032]$], which supports bulk approve/reject actions. Selecting multiple items and choosing "Reject" removes the PII tag and logs the action.

### How to Audit Classifier Overrides

All override actions are automatically captured in the audit log per [$[DPLAT-042]$]. Each entry is created within 500ms and includes:

- User ID and workspace-admin's full name and email
- Timestamp
- Original classification and new classification
- Data record identifier
- Specific data source (connector) where the override occurred

The audit log uses **SHA-256 hash chaining** — each entry contains an immutable hash linking to the previous entry, preventing retroactive tampering. Compliance officers can filter the Audit Log Export by "override" action type and date range to retrieve all matching PII override entries.

### Workflow for Tag Review

The complete tag review workflow involves:

1. **Access the review interface** — Workspace admins navigate to the review interface showing all auto-classified fields with confidence scores and suggested PII categories (from [$[DPLAT-013]$]).

2. **Review flagged items** — For false-positive scenarios, compliance officers use the dedicated review queue from [$[DPLAT-032]$], which lists flagged items with source field, detected PII type, and confidence score.

3. **Take action** — Options include:
   - **Override individually**: Select an alternative PII category from the dropdown
   - **Bulk Approve**: Confirm items as true PII (retains PII tag and retention policy)
   - **Bulk Reject**: Mark as false positive (removes PII tag and removes from review queue)

4. **Audit logging** — Every action generates an audit log entry with full traceability, including the workspace-admin's identity, timestamp, original and new classifications, and data source.

5. **Training feedback** — Overridden classifications are fed back into the system to improve future automated detection accuracy (per [$[DPLAT-013]$] acceptance criteria).

**Sources:**
- 📋 [[DPLAT-013] PII tagging — workspace-admin can review and override classifier decisions](https://demo-jira.local/browse/DPLAT-013)
- 📄 [PII Auto-Tagging — Policy and Behavior](https://demo-confluence.local/wiki/spaces/DPLAT/pages/88678288ed34)
- 📋 [[DPLAT-042] Audit Log — capture all PII override decisions automatically](https://demo-jira.local/browse/DPLAT-042)
- 📄 [pii-classifier-service — README](https://demo-bitbucket.local/pii-classifier-service/blob/main/README.md)
- 📄 [compliance-vault — README](https://demo-bitbucket.local/compliance-vault/blob/main/README.md)
- 📋 [[DPLAT-032] PII — false-positive review queue with bulk approve/reject](https://demo-jira.local/browse/DPLAT-032)
- 📋 [[DPLAT-006] PII tagging — per-tenant retention override (default 60 days)](https://demo-jira.local/browse/DPLAT-006)
- 📋 [[DPLAT-DEF-06] PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style](https://demo-jira.local/browse/DPLAT-DEF-06)
- 📋 [[DPLAT-EPIC-04] PII Auto-Tagging](https://demo-jira.local/browse/DPLAT-EPIC-04)
- 📋 [[DPLAT-DEF-17] PII — Italian fiscal-code regex mistakenly tags valid order IDs](https://demo-jira.local/browse/DPLAT-DEF-17)
- 📋 [[DPLAT-DEF-07] PII tagging skips email addresses inside CSV imports (only scans first 100 rows)](https://demo-jira.local/browse/DPLAT-DEF-07)
- 📋 [[DPLAT-DEF-16] PII — classifier crashes on documents larger than 1MB](https://demo-jira.local/browse/DPLAT-DEF-16)
- 📋 [[DPLAT-005] PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest design)](https://demo-jira.local/browse/DPLAT-005)
- 📄 [PII Classifier — Evaluation Methodology](https://demo-confluence.local/wiki/spaces/DPLAT/pages/0ba267efc858)
- 📋 [[DPLAT-034] PII — bulk re-classification job for historical data](https://demo-jira.local/browse/DPLAT-034)
