---
space: DPLAT
slug: 04-salesforce-connector-business-rules
title: "Salesforce Connector — Business Rules"
parent_slug: 02-connector-framework-overview
labels:
  - module:connector-framework
  - feature:F-A1
  - doc-type:business-rules
  - source-of-truth
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-18T14:00:00Z
version: 7
status: current
linked_jira:
  - DPLAT-001
  - DPLAT-002
  - DPLAT-003
  - DPLAT-REQ-03
---

# Salesforce Connector — Business Rules

## Purpose

This document defines the business rules governing the Salesforce Connector within the DPLAT connector framework. The Salesforce Connector enables bi-directional synchronization between Salesforce orgs and DPLAT workspaces, supporting use cases such as lead routing, opportunity tracking, and customer 360° views.

This document serves as the authoritative reference for workspace admins, compliance officers, and integration engineers configuring Salesforce integrations within their tenant.

## Object scope

The Salesforce Connector supports the following standard objects out of the box:

| Object | Read | Write | Delete | Notes |
|--------|------|-------|--------|-------|
| Account | ✅ | ✅ | ❌ | Full support |
| Contact | ✅ | ✅ | ❌ | PII-sensitive; requires consent flag |
| Lead | ✅ | ✅ | ❌ | Conversion tracking enabled |
| Opportunity | ✅ | ✅ | ❌ | Stage mapping configurable |
| Case | ✅ | ✅ | ❌ | Support ticket sync |
| Custom Objects | ✅ | ⚠️ | ❌ | Requires schema registration |

Custom objects require explicit schema registration via the Connector Configuration API. Workspace admins must define field mappings and transformation rules before enabling custom object sync.

## Sync frequency

The Salesforce Connector supports three sync frequency modes:

- **Near real-time (webhook-driven):** Triggers on create/update events via Platform Events. Latency: < 5 seconds. Available on Enterprise and Unlimited editions.
- **Scheduled batch (hourly):** Full delta sync every hour. Suitable for high-volume orgs.
- **Scheduled batch (daily):** Full snapshot sync at midnight UTC. Lowest API consumption.

Default mode is **near real-time** for standard objects and **hourly batch** for custom objects. Workspace admins may override per-object in the Connector Configuration UI.

## Authentication

The Salesforce Connector uses **OAuth 2.0** for authentication, following the Salesforce Connected App flow. This approach is referenced in DPLAT-003 and DPLAT-REQ-03.

Authentication flow:

1. Workspace admin initiates connector setup and is redirected to Salesforce login.
2. User grants permissions via Salesforce OAuth consent screen.
3. DPLAT receives authorization code and exchanges it for access token + refresh token.
4. Tokens are stored encrypted in the tenant's secure vault.
5. Access tokens are automatically refreshed before expiration (60-minute TTL).

Required OAuth scopes:
- `api` — Full API access
- `refresh_token` — Long-lived refresh capability
- `webhook` — Platform Events subscription (for real-time sync)

## Error handling

The connector implements the following error handling semantics:

| Error Type | Behavior | Audit Log Entry |
|------------|----------|-----------------|
| API 4xx (client error) | Retry 2x with exponential backoff, then quarantine | `ERROR_4XX` with payload |
| API 5xx (server error) | Retry 5x over 15 minutes, then alert admin | `ERROR_5XX` with stack trace |
| Rate limit (429) | Throttle and queue; resume when header allows | `RATE_LIMITED` |
| Network timeout | Retry 3x; mark record as `SYNC_PENDING` | `TIMEOUT` |
| Schema mismatch | Skip field; log warning; continue sync | `SCHEMA_DRIFT` |

Quarantined records are retained for 7 days and can be manually reprocessed via the Connector UI. Compliance officers can export quarantine logs for audit purposes.

## Retention of cached data

The Salesforce Connector maintains a local cache of synced records to optimize read performance and support offline change detection. **The default retention period for cached Salesforce data is 30 days, after which records are automatically purged from the cache.** Workspace admins may configure extended retention (up to 90 days) for compliance requirements, subject to additional storage costs.

Cached data includes:
- Full record snapshots (all synced fields)
- Change tracking metadata (last modified timestamp, modifying user)
- Relationship pointers (parent-child links)

Note: Cached data is never exposed outside the tenant boundary and is encrypted at rest using AES-256.

## Setup prerequisites

Before configuring the Salesforce Connector, workspace admins must complete the following:

### IP Allowlist Requirement

As referenced in DPLAT-DEF-02, Salesforce requires that DPLAT outbound IP addresses be allowlisted in the target org. Workspace admins must add the following IP ranges to their Salesforce network access settings:

```
# DPLAT US-East (Primary)
203.0.113.0/24

# DPLAT EU-West (Failover)
198.51.100.0/24
```

Request IP allowlist documentation via the tenant support portal.

### Required Permissions

The Salesforce user performing OAuth setup must have:
- `Customize Application` permission
- `Manage Connected Apps` permission
- Object-level CRUD on target objects (Account, Contact, etc.)

### Connected App Configuration

A DPLAT-managed Connected App must be created in the target Salesforce org:
1. Navigate to Setup → App Manager → New Connected App
2. Enable "Enable OAuth Settings"
3. Add callback URL: `https://connect.dplat.io/oauth/salesforce/callback`
4. Set OAuth scopes as listed in the Authentication section