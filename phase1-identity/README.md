# Phase 1: Identity

## Goal
Okta signs users in to three apps. A Python tool runs join, move and leave. Terraform manages groups.

## Fictional company
- Groups: Engineering, Sales, Ops, Leadership, All-Staff
- Users: 10 (plus-addressed emails)

## How it works
_TODO: architecture diagram and description._

### SSO
- Google Workspace (SAML)
- Salesforce Developer Edition (SAML)
- Northwind intranet (OIDC)

### Provisioning
_TODO_

### JML tool
See [jml-tool/](jml-tool/).

### Terraform
See [terraform/](terraform/).

## Screenshots
See [screenshots/](screenshots/). Blur every org URL.

## What I learned
_TODO_
