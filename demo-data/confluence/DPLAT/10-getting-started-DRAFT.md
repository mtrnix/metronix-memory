---
space: DPLAT
slug: 10-getting-started-DRAFT
title: "Getting Started Guide (Draft)"
parent_slug: 01-product-overview
labels:
  - doc-type:draft
author: ariel@mtrnix.example
created: 2026-01-12T08:00:00Z
updated: 2026-03-15T16:00:00Z
version: 2
status: draft
linked_jira: []
---

# Getting Started Guide (Draft)

This guide walks you through the initial setup of your DPLAT environment. After completing these steps, you will have an active workspace with team members ready to configure data pipelines.

## Before You Begin

Ensure you have the following:

- An invitation email from your organization's **tenant administrator**
- Access credentials for your identity provider (if using SSO)
- A list of team members who will need access, along with their email addresses

## Logging in for the First Time

### Receive Your Invitation

When your tenant administrator creates your DPLAT account, you will receive an email with a unique invitation link. This link is valid for 7 days.

### Choose Your Authentication Method

DPLAT supports multiple authentication options:

| Method | Description |
|--------|-------------|
| Email + Password | Direct registration with a verified email address |
| SAML SSO | Single Sign-On via your organization's identity provider |
| OAuth | Login via Google, Microsoft, or other supported providers |

### Complete Initial Setup

After authenticating, you will be prompted to:

1. **Verify your email address** — A confirmation code will be sent to your inbox
2. **Set up multi-factor authentication (MFA)** — Required for workspace administrators
3. **Accept the Data Processing Agreement** — Required for handling PII

> **Note:** MFA can be configured later in your Account Settings, but workspace administrators must complete MFA before creating their first workspace.

## Creating a Workspace

A **workspace** is the primary organizational unit in DPLAT. Each workspace contains its own set of connectors, data sources, audit logs, and team members.

### Workspace Creation Steps

1. From the homepage, click **Create New Workspace**
2. Enter a workspace name (e.g., "Marketing Data Platform" or "Customer Analytics")
3. Select your organization's **data residency region** — This determines where your data will be stored
4. Choose a **workspace icon** (optional)
5. Click **Create Workspace**

### Workspace Naming Best Practices

| Do | Don't |
|----|-------|
| Use descriptive names: "EU Customer Data" | Use generic names: "Workspace 1" |
| Include region or team: "APAC-Sales" | Use special characters or spaces |
| Follow your organization's naming convention | Use names that reveal sensitive information |

### Understanding Workspace Limits

| Tier | Workspaces per Tenant |
|------|----------------------|
| Starter | 1 |
| Professional | 5 |
| Enterprise | Unlimited |

## Inviting Team Members

After creating a workspace, you can invite team members with appropriate access levels.

### Available Roles

| Role | Description | Can Configure Connectors | Can View PII | Can Manage Retention |
|------|-------------|-------------------------|--------------|---------------------|
| **Workspace Admin** | Full access to workspace settings | ✅ | ✅ | ✅ |
| **Data Engineer** | Build and maintain data pipelines | ✅ | ✅ | ❌ |
| **Analyst** | Read-only access to processed data | ❌ | ✅ | ❌ |
| **Viewer** | Limited read access, no PII | ❌ | ❌ | ❌ |
| **Compliance Officer** | Audit and governance access | ❌ | ✅ | ✅ |

### Sending Invitations

1. Navigate to **Workspace Settings > Team**
2. Click **Invite Members**
3. Enter email addresses (one per line, or comma-separated)
4. Select the appropriate role for each invitee
5. Optionally add a personalized message
6. Click **Send Invitations**

### What Happens Next

- Each invitee receives an email with a link to join the workspace
- If they already have a DPLAT account, they will be automatically added to the workspace
- If not, they will be prompted to create an account
- Workspace admins will see pending invitations in the Team settings

## Verifying Your Setup

Before proceeding, confirm that:

- [ ] You can log in successfully
- [ ] MFA is enabled on your account
- [ ] Your workspace has been created with the correct name
- [ ] At least one team member has been invited
- [ ] You have received confirmation emails

## What's Next

You are now ready to configure your data pipelines. Continue to the **Connector Setup Guide** to begin integrating your data sources.