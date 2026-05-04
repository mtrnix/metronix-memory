# DPLAT Demo — Source Artifacts Index

_Generated 2026-05-04 18:39 UTC · demo-only, will be removed after the Amisol demo._

Every entry below is one synthetic artifact that was ingested into the `dplat-demo` workspace. Links open the underlying file (rendered nicely by GitHub for `.json` and `.md`).

Quality-signal badges flag artifacts that participate in a deliberate demo moment — pick any with **C1 / C1b / C2 / C2b / C4 / C6** to drill into the headline scenes.

---

## Jira (86 artifacts)

### Epics (5)

| Key | Type | Status | Summary | Signal |
|-----|------|--------|---------|--------|
| [`DPLAT-EPIC-01`](../../demo-data/jira/DPLAT-EPIC-01.json) | Epic | In Progress | Salesforce Connector |  |
| [`DPLAT-EPIC-02`](../../demo-data/jira/DPLAT-EPIC-02.json) | Epic | In Progress | SAP S/4HANA Connector |  |
| [`DPLAT-EPIC-03`](../../demo-data/jira/DPLAT-EPIC-03.json) | Epic | In Progress | Connector Health Monitor |  |
| [`DPLAT-EPIC-04`](../../demo-data/jira/DPLAT-EPIC-04.json) | Epic | In Progress | PII Auto-Tagging |  |
| [`DPLAT-EPIC-05`](../../demo-data/jira/DPLAT-EPIC-05.json) | Epic | In Progress | Audit Log Export |  |

### User Stories (43)

| Key | Type | Status | Summary | Signal |
|-----|------|--------|---------|--------|
| [`DPLAT-001`](../../demo-data/jira/DPLAT-001.json) | Story | Done | Connector Framework — configuration schema and validation layer |  |
| [`DPLAT-002`](../../demo-data/jira/DPLAT-002.json) | Story | Done | Salesforce connector — initial setup wizard | `C4 cross-link` |
| [`DPLAT-003`](../../demo-data/jira/DPLAT-003.json) | Story | In Progress | Salesforce connector — OAuth token refresh and session management |  |
| [`DPLAT-004`](../../demo-data/jira/DPLAT-004.json) | Story | Done | SAP S/4HANA connector — initial setup wizard |  |
| [`DPLAT-005`](../../demo-data/jira/DPLAT-005.json) | Story | Done | PII classifier — hybrid rule + ML pipeline at ingestion (replaces legacy post-ingest desig | `C2 supersedes conf-09` |
| [`DPLAT-006`](../../demo-data/jira/DPLAT-006.json) | Story | In Progress | PII tagging — per-tenant retention override (default 60 days) | `C1 conflict (60d)` |
| [`DPLAT-007`](../../demo-data/jira/DPLAT-007.json) | Story | Done | Health Monitor dashboard — connector status overview for admins |  |
| [`DPLAT-008`](../../demo-data/jira/DPLAT-008.json) | Story | In Progress | Health Monitor — alerting on connector sync failures (PagerDuty + email) |  |
| [`DPLAT-009`](../../demo-data/jira/DPLAT-009.json) | Story | Done | Audit Log Export — scheduled CSV export to S3 bucket |  |
| [`DPLAT-010`](../../demo-data/jira/DPLAT-010.json) | Story | Done | Audit Log Export — compliance officer can trigger ad-hoc export with date range |  |
| [`DPLAT-011`](../../demo-data/jira/DPLAT-011.json) | Story | Done | SAP S/4HANA connector — incremental delta sync via OData change tokens |  |
| [`DPLAT-012`](../../demo-data/jira/DPLAT-012.json) | Story | In Progress | SAP S/4HANA connector — handle large result sets via paging and stream processing |  |
| [`DPLAT-013`](../../demo-data/jira/DPLAT-013.json) | Story | Done | PII tagging — workspace-admin can review and override classifier decisions |  |
| [`DPLAT-014`](../../demo-data/jira/DPLAT-014.json) | Story | In Progress | Audit Log Export — encrypted archive format with signed manifest |  |
| [`DPLAT-015`](../../demo-data/jira/DPLAT-015.json) | Story | To Do | Audit Log Export — ServiceNow integration for ITSM ticketing of findings |  |
| [`DPLAT-016`](../../demo-data/jira/DPLAT-016.json) | Story | Done | Salesforce — field-mapping UI for custom object aliases |  |
| [`DPLAT-017`](../../demo-data/jira/DPLAT-017.json) | Story | Done | Salesforce — bulk migration tool from legacy v1 connector |  |
| [`DPLAT-018`](../../demo-data/jira/DPLAT-018.json) | Story | Done | Salesforce — sync error retry queue with dead-letter handling |  |
| [`DPLAT-019`](../../demo-data/jira/DPLAT-019.json) | Story | In Progress | Salesforce — record deletion propagation policy |  |
| [`DPLAT-020`](../../demo-data/jira/DPLAT-020.json) | Story | To Do | Salesforce — usage metrics dashboard by object type |  |
| [`DPLAT-021`](../../demo-data/jira/DPLAT-021.json) | Story | Done | SAP — table whitelist configuration UI |  |
| [`DPLAT-022`](../../demo-data/jira/DPLAT-022.json) | Story | Done | SAP — BAPI vs OData transport decision matrix |  |
| [`DPLAT-023`](../../demo-data/jira/DPLAT-023.json) | Story | In Progress | SAP — legacy SAP ECC 6.0 compatibility mode |  |
| [`DPLAT-024`](../../demo-data/jira/DPLAT-024.json) | Story | To Do | SAP — multi-system aggregation across DEV/QAS/PRD |  |
| [`DPLAT-025`](../../demo-data/jira/DPLAT-025.json) | Story | Done | SAP — field type mapping for German locale (DECIMAL/NUMC/CHAR) |  |
| [`DPLAT-026`](../../demo-data/jira/DPLAT-026.json) | Story | Done | Health Monitor — per-tenant filter and view scoping |  |
| [`DPLAT-027`](../../demo-data/jira/DPLAT-027.json) | Story | Done | Health Monitor — Datadog metrics exporter integration |  |
| [`DPLAT-028`](../../demo-data/jira/DPLAT-028.json) | Story | In Progress | Health Monitor — weekly digest email to admin role |  |
| [`DPLAT-029`](../../demo-data/jira/DPLAT-029.json) | Story | Done | Audit Log v2 architecture — replaces v1 single-table design (legacy) | `C2b supersedes conf-19` |
| [`DPLAT-030`](../../demo-data/jira/DPLAT-030.json) | Story | Done | Connector recovery SLA — 60-minute target after upstream outage | `C1b conflict (60m)` |
| [`DPLAT-031`](../../demo-data/jira/DPLAT-031.json) | Story | Done | PII — nested JSON field traversal up to 5 levels deep |  |
| [`DPLAT-032`](../../demo-data/jira/DPLAT-032.json) | Story | Done | PII — false-positive review queue with bulk approve/reject |  |
| [`DPLAT-033`](../../demo-data/jira/DPLAT-033.json) | Story | In Progress | PII — training-set update flow with versioned model registry |  |
| [`DPLAT-034`](../../demo-data/jira/DPLAT-034.json) | Story | To Do | PII — bulk re-classification job for historical data |  |
| [`DPLAT-035`](../../demo-data/jira/DPLAT-035.json) | Story | Done | PII — API rate limiting per tenant (max 1k req/min) |  |
| [`DPLAT-036`](../../demo-data/jira/DPLAT-036.json) | Story | Done | Audit Log — archival to S3 Glacier after 90 days |  |
| [`DPLAT-037`](../../demo-data/jira/DPLAT-037.json) | Story | In Progress | Audit Log — full-text search across historical exports |  |
| [`DPLAT-038`](../../demo-data/jira/DPLAT-038.json) | Story | Done | Audit Log — pre-signed URL for download (24h expiry) |  |
| [`DPLAT-039`](../../demo-data/jira/DPLAT-039.json) | Story | To Do | Audit Log — batch sign-off workflow for compliance officer |  |
| [`DPLAT-040`](../../demo-data/jira/DPLAT-040.json) | Story | Done | Audit Log — export format selector (CSV / Parquet / JSON-NDJSON) |  |
| [`DPLAT-041`](../../demo-data/jira/DPLAT-041.json) | Story | Done | Health Monitor — surface PII classifier latency metrics |  |
| [`DPLAT-042`](../../demo-data/jira/DPLAT-042.json) | Story | Done | Audit Log — capture all PII override decisions automatically |  |
| [`DPLAT-043`](../../demo-data/jira/DPLAT-043.json) | Story | Done | Health Monitor — include Audit Log Export job status panel |  |

### Requirements (20)

| Key | Type | Status | Summary | Signal |
|-----|------|--------|---------|--------|
| [`DPLAT-REQ-01`](../../demo-data/jira/DPLAT-REQ-01.json) | Task | Done | Connector data sync latency budget — 99p < 5 minutes per 10k records |  |
| [`DPLAT-REQ-02`](../../demo-data/jira/DPLAT-REQ-02.json) | Task | Done | Connector framework rate-limiting — fairness across tenants |  |
| [`DPLAT-REQ-03`](../../demo-data/jira/DPLAT-REQ-03.json) | Task | Done | Salesforce OAuth token storage — AES-256 encryption at rest |  |
| [`DPLAT-REQ-04`](../../demo-data/jira/DPLAT-REQ-04.json) | Task | Done | SAP connector throughput — sustain 5k records/min for full sync |  |
| [`DPLAT-REQ-05`](../../demo-data/jira/DPLAT-REQ-05.json) | Task | Done | Health Monitor uptime — 99.9% availability for status read API |  |
| [`DPLAT-REQ-06`](../../demo-data/jira/DPLAT-REQ-06.json) | Task | Done | PII classifier accuracy — precision >= 0.95 on EN/DE/FR validation set |  |
| [`DPLAT-REQ-07`](../../demo-data/jira/DPLAT-REQ-07.json) | Task | Done | PII data residency — classifier inference must run in tenant-region only |  |
| [`DPLAT-REQ-08`](../../demo-data/jira/DPLAT-REQ-08.json) | Task | Done | Audit Log Export — full export of 90 days fits in 4 GB compressed CSV |  |
| [`DPLAT-REQ-09`](../../demo-data/jira/DPLAT-REQ-09.json) | Task | Done | Audit Log integrity — every record is hash-chained for tamper detection |  |
| [`DPLAT-REQ-10`](../../demo-data/jira/DPLAT-REQ-10.json) | Task | Done | Audit Log Export — RBAC: only Compliance Officer role can trigger export |  |
| [`DPLAT-REQ-11`](../../demo-data/jira/DPLAT-REQ-11.json) | Task | Done | Connector framework — TLS 1.3 minimum for outbound connections |  |
| [`DPLAT-REQ-12`](../../demo-data/jira/DPLAT-REQ-12.json) | Task | Done | Salesforce — respect upstream API rate limits with adaptive backoff |  |
| [`DPLAT-REQ-13`](../../demo-data/jira/DPLAT-REQ-13.json) | Task | Done | SAP — support both SOAP and OData v4 transport |  |
| [`DPLAT-REQ-14`](../../demo-data/jira/DPLAT-REQ-14.json) | Task | Done | Health Monitor — 1s p99 read latency for status API |  |
| [`DPLAT-REQ-15`](../../demo-data/jira/DPLAT-REQ-15.json) | Task | Done | Connector recovery — operational runbook target is 30 minutes | `C1b conflict (30m)` |
| [`DPLAT-REQ-16`](../../demo-data/jira/DPLAT-REQ-16.json) | Task | Done | PII — model inference must run within tenant geo-region |  |
| [`DPLAT-REQ-17`](../../demo-data/jira/DPLAT-REQ-17.json) | Task | Done | PII — false-negative rate target ≤ 0.02 on regulatory test set |  |
| [`DPLAT-REQ-18`](../../demo-data/jira/DPLAT-REQ-18.json) | Task | Done | Audit Log — write throughput sustains 10k events/sec per tenant |  |
| [`DPLAT-REQ-19`](../../demo-data/jira/DPLAT-REQ-19.json) | Task | Done | Audit Log — encryption-at-rest with tenant-managed keys (BYOK) |  |
| [`DPLAT-REQ-20`](../../demo-data/jira/DPLAT-REQ-20.json) | Task | Done | Audit Log — schema versioning with backward compatibility for 2y |  |

### Defects (Bugs) (18)

| Key | Type | Status | Summary | Signal |
|-----|------|--------|---------|--------|
| [`DPLAT-DEF-01`](../../demo-data/jira/DPLAT-DEF-01.json) | Bug | Open | Health Monitor raises false positive on connector with paused status |  |
| [`DPLAT-DEF-02`](../../demo-data/jira/DPLAT-DEF-02.json) | Bug | Open | Salesforce setup wizard fails silently when sandbox org has restricted IP allowlist | `C4 cross-link` |
| [`DPLAT-DEF-03`](../../demo-data/jira/DPLAT-DEF-03.json) | Bug | In Progress | SAP connector sync hangs indefinitely on OData paging cursor expiry |  |
| [`DPLAT-DEF-04`](../../demo-data/jira/DPLAT-DEF-04.json) | Bug | Open | Default retention for cached connector data is 90 days, not 30 days as documented | `C1 conflict (90d)` |
| [`DPLAT-DEF-05`](../../demo-data/jira/DPLAT-DEF-05.json) | Bug | In Progress | Audit Log Export ad-hoc range fails with timezone offset for non-UTC users |  |
| [`DPLAT-DEF-06`](../../demo-data/jira/DPLAT-DEF-06.json) | Bug | Open | PII classifier mislabels German postal codes as PII when format is 4-digit Austrian style |  |
| [`DPLAT-DEF-07`](../../demo-data/jira/DPLAT-DEF-07.json) | Bug | Open | PII tagging skips email addresses inside CSV imports (only scans first 100 rows) | `C6 defect ≠ behavior` |
| [`DPLAT-DEF-08`](../../demo-data/jira/DPLAT-DEF-08.json) | Bug | Open | Health Monitor dashboard shows stale 'last sync' timestamp after manual restart of connect |  |
| [`DPLAT-DEF-09`](../../demo-data/jira/DPLAT-DEF-09.json) | Bug | Open | Salesforce — sync drops attachments larger than 5MB |  |
| [`DPLAT-DEF-10`](../../demo-data/jira/DPLAT-DEF-10.json) | Bug | Open | Salesforce — wizard browser focus lost after OAuth redirect |  |
| [`DPLAT-DEF-11`](../../demo-data/jira/DPLAT-DEF-11.json) | Bug | Open | SAP — connector returns null for German umlauts in CHAR fields |  |
| [`DPLAT-DEF-12`](../../demo-data/jira/DPLAT-DEF-12.json) | Bug | In Progress | SAP — delta sync skips records updated within 1s of last cursor |  |
| [`DPLAT-DEF-13`](../../demo-data/jira/DPLAT-DEF-13.json) | Bug | Open | Health Monitor — dashboard takes >10s to load with 50+ connectors |  |
| [`DPLAT-DEF-14`](../../demo-data/jira/DPLAT-DEF-14.json) | Bug | Open | Health Monitor — alert deduplication merges unrelated incidents |  |
| [`DPLAT-DEF-15`](../../demo-data/jira/DPLAT-DEF-15.json) | Bug | Open | Connector recovery actually takes ~4 hours after Salesforce-side outage | `C1b conflict (4h)` |
| [`DPLAT-DEF-16`](../../demo-data/jira/DPLAT-DEF-16.json) | Bug | In Progress | PII — classifier crashes on documents larger than 1MB |  |
| [`DPLAT-DEF-17`](../../demo-data/jira/DPLAT-DEF-17.json) | Bug | Open | PII — Italian fiscal-code regex mistakenly tags valid order IDs |  |
| [`DPLAT-DEF-18`](../../demo-data/jira/DPLAT-DEF-18.json) | Bug | In Progress | Audit Log — export job queue can deadlock if 4+ exports queued |  |

## Confluence (21 pages)

| Page | Status | Title | Signal |
|------|--------|-------|--------|
| [`01-product-overview`](../../demo-data/confluence/DPLAT/01-product-overview.md) | current | Amisol DataPlatform Demo — Product Overview |  |
| [`02-connector-framework-overview`](../../demo-data/confluence/DPLAT/02-connector-framework-overview.md) | current | Connector Framework — Module Overview |  |
| [`03-compliance-vault-overview`](../../demo-data/confluence/DPLAT/03-compliance-vault-overview.md) | current | Compliance Vault — Module Overview |  |
| [`04-salesforce-connector-business-rules`](../../demo-data/confluence/DPLAT/04-salesforce-connector-business-rules.md) | current | Salesforce Connector — Business Rules | `C1 source-of-truth (30d)` |
| [`05-pii-auto-tagging-policy`](../../demo-data/confluence/DPLAT/05-pii-auto-tagging-policy.md) | current | PII Auto-Tagging — Policy and Behavior | `C1 platform policy (30d)` |
| [`06-connector-config-api`](../../demo-data/confluence/DPLAT/06-connector-config-api.md) | current | Connector Configuration API — Reference |  |
| [`07-salesforce-connector-troubleshooting`](../../demo-data/confluence/DPLAT/07-salesforce-connector-troubleshooting.md) | current | Salesforce Connector — Troubleshooting Guide |  |
| [`08-release-notes-v2-3`](../../demo-data/confluence/DPLAT/08-release-notes-v2-3.md) | current | Release Notes — v2.3 (April 2026) |  |
| [`09-pii-tagging-initial-design-LEGACY`](../../demo-data/confluence/DPLAT/09-pii-tagging-initial-design-LEGACY.md) | 🕒 **superseded** | PII Tagging — Initial Design (Legacy) | `C2 stale (legacy 2024)` |
| [`10-getting-started-DRAFT`](../../demo-data/confluence/DPLAT/10-getting-started-DRAFT.md) | _draft_ | Getting Started Guide (Draft) |  |
| [`11-connector-framework-architecture`](../../demo-data/confluence/DPLAT/11-connector-framework-architecture.md) | current | Connector Framework — Architecture Deep-Dive |  |
| [`12-pii-classifier-evaluation-methodology`](../../demo-data/confluence/DPLAT/12-pii-classifier-evaluation-methodology.md) | current | PII Classifier — Evaluation Methodology |  |
| [`13-audit-log-query-reference`](../../demo-data/confluence/DPLAT/13-audit-log-query-reference.md) | current | Audit Log — Query Language Reference |  |
| [`14-release-notes-v2-4-planned`](../../demo-data/confluence/DPLAT/14-release-notes-v2-4-planned.md) | current | Release Notes — v2.4 (Planned) |  |
| [`15-connector-ops-runbook`](../../demo-data/confluence/DPLAT/15-connector-ops-runbook.md) | current | Connector Operations Runbook | `C1b runbook (30m)` |
| [`19-audit-log-v1-architecture-LEGACY`](../../demo-data/confluence/DPLAT/19-audit-log-v1-architecture-LEGACY.md) | 🕒 **superseded** | Audit Log v1 Architecture (Legacy) | `C2b stale (legacy 2024)` |
| [`20-sprint-18-retro-notes`](../../demo-data/confluence/DPLAT/20-sprint-18-retro-notes.md) | current | Sprint 18 Retro — Action Items |  |
| [`21-team-okr-q2-2026`](../../demo-data/confluence/DPLAT/21-team-okr-q2-2026.md) | current | Engineering Team — Q2 2026 OKRs |  |
| [`22-customer-success-faq`](../../demo-data/confluence/DPLAT/22-customer-success-faq.md) | current | Customer Success — Internal FAQ |  |
| [`23-engineering-offsite-notes`](../../demo-data/confluence/DPLAT/23-engineering-offsite-notes.md) | current | Engineering Offsite — Berlin 2026 |  |
| [`24-adr-007-postgres-vs-clickhouse`](../../demo-data/confluence/DPLAT/24-adr-007-postgres-vs-clickhouse.md) | current | ADR-007 — Storage Backend for Audit Log (Postgres vs ClickHouse) |  |

## Bitbucket READMEs (6 repos)

| Repo | File |
|------|------|
| `audit-log-service` | [README.md](../../demo-data/bitbucket/audit-log-service/README.md) |
| `compliance-vault` | [README.md](../../demo-data/bitbucket/compliance-vault/README.md) |
| `connector-framework` | [README.md](../../demo-data/bitbucket/connector-framework/README.md) |
| `health-monitor-ui` | [README.md](../../demo-data/bitbucket/health-monitor-ui/README.md) |
| `pii-classifier-service` | [README.md](../../demo-data/bitbucket/pii-classifier-service/README.md) |
| `shared-libs` | [README.md](../../demo-data/bitbucket/shared-libs/README.md) |

---

## Quality-signal index (demo drill-down)

Open any of the artifacts below to find the source-text behind a demo moment.

### C1 — retention conflict (30d / 60d / 90d)

- `DPLAT-DEF-04` — C1 conflict (90d)
- `DPLAT-006` — C1 conflict (60d)
- `conf-04` — C1 source-of-truth (30d)
- `conf-05` — C1 platform policy (30d)

### C1b — connector recovery SLA conflict (30m / 60m / 4h)

- `DPLAT-030` — C1b conflict (60m)
- `DPLAT-DEF-15` — C1b conflict (4h)
- `DPLAT-REQ-15` — C1b conflict (30m)
- `conf-15` — C1b runbook (30m)

### C2 — PII classifier staleness (legacy 2024 → current)

- `conf-09` — C2 stale (legacy 2024)
- `DPLAT-005` — C2 supersedes conf-09

### C2b — Audit Log v1 staleness (legacy 2024 → current)

- `conf-19` — C2b stale (legacy 2024)
- `DPLAT-029` — C2b supersedes conf-19

### C4 — cross-source linking (DPLAT-002 ↔ conf-04 ↔ DPLAT-DEF-02)

- `DPLAT-002` — C4 cross-link
- `DPLAT-DEF-02` — C4 cross-link

### C6 — defect-not-behavior (DPLAT-DEF-07 must NOT propagate to user guide)

- `DPLAT-DEF-07` — C6 defect ≠ behavior
