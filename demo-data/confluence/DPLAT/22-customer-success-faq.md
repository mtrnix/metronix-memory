---
space: DPLAT
slug: 22-customer-success-faq
title: "Customer Success — Internal FAQ"
parent_slug: 01-product-overview
labels:
  - doc-type:faq
  - team:cs
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-04-05T09:00:00Z
version: 3
status: current
linked_jira: []
---

# Customer Success — Internal FAQ

This document provides standardized answers for common customer-facing questions. Use these responses as a baseline and customize per customer context.

## Pricing & Billing

### Q: Can we provide discounts for annual commitments?

A: Yes. Standard discount guidance:
- **Annual prepay**: Up to 15% off monthly equivalent
- **Multi-year (3 years)**: Up to 25% off monthly equivalent
- **Enterprise custom**: Requires VP Sales + Finance approval

Discounts apply to base platform fees. Connector add-ons and professional services are negotiated separately. Document all discounts in the opportunity record before quoting.

### Q: How are overage charges calculated?

A: Overage is billed at the start of the following billing cycle, not prorated within the current cycle. Customers receive an email notification when usage reaches 80% and 100% of their allocated volume.

For tenants approaching overage, proactively share usage trends via the audit log dashboard and recommend a plan adjustment if sustained growth is detected.

### Q: What happens if a customer misses a payment?

A: Billing follows this escalation path:
- **Day 1–7 overdue**: Automated email reminders; service continues
- **Day 8–14 overdue**: CS reaches out directly; connector syncs pause after Day 10
- **Day 15+ overdue**: Account placed in "payment review" status; full service suspension until resolved

Workspace admins can reactivate service immediately upon payment confirmation. Retention policies remain active during suspension.

## Support Operations

### Q: How do we escalate critical production issues?

A: Use the severity matrix:

| Severity | Description | Response SLA |
|----------|-------------|--------------|
| SEV-1 | Complete outage, data loss, or PII exposure | 1 hour, 24/7 |
| SEV-2 | Major feature broken, workaround unavailable | 4 business hours |
| SEV-3 | Minor functionality impacted, workaround exists | 1 business day |
| SEV-4 | General questions, feature requests | 2 business days |

SEV-1 incidents require immediate page to the on-call engineer via PagerDuty. CS must stay engaged until resolution confirmation.

### Q: When should we involve Professional Services?

A: Escalate to PS for:
- Custom connector development or modification
- Complex data mapping exceeding 40+ fields
- On-premises deployment requirements
- Training sessions over 4 hours

PS engagement requires a separate statement of work. CS can book an initial discovery call at no cost.

## Legal & Compliance

### Q: What is the NDA process for sharing customer data with Mtrnix engineers?

A: For debugging or support analysis:
1. Customer must explicitly consent in writing (email acceptable)
2. Reference the specific tenant and data scope
3. Redact PII where possible; use test data when feasible
4. Store consent record in the support ticket

Our standard NDA is bilateral and available via the sales team. Pre-signed NDAs exist for select enterprise customers — verify in the CRM before requesting a new execution.

### Q: Can customers request deletion of their audit log data?

A: Audit log retention follows this policy:
- **Standard tier**: 90 days, then archived
- **Enterprise tier**: 1 year, then archived
- **Archived data**: Retained for 7 years for compliance, then permanently deleted

Customers can request expedited deletion with a 30-day processing window. Archived data deletion requires Legal review and may incur a fee.

## Account Management

### Q: How do we handle workspace admin changes?

A: Admin role changes require:
1. Email from the existing admin or company domain email
2. Full name and email of the new admin
3. Confirmation that the requester is authorized

For disputed admin changes, verify via phone with the company's registered contact before proceeding. Document all changes in the ticket.

### Q: What is the process for tenant consolidation or migration?

A: Cross-tenant data migration requires:
- Professional Services engagement
- Minimum 2-week lead time
- One-time fee based on data volume

Customers can self-serve migration within the same tenant by exporting via the data export connector and importing into a new workspace.