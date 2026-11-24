# Startup IT Lab

A home lab for practicing IT work at a startup. The fictional company is **Tallow Peak** (`tallowpeak-lab.com`).

> This is lab work. Nothing here is a production environment.

## Status

**Phase 1 (Identity) is in progress.** Working so far:

- **Okta** as the identity provider, with departments as groups and YubiKey MFA for admins
- **SSO** to Salesforce (SAML) and a custom intranet app (OIDC) with group-based access and step-up MFA
- **Joiner/mover/leaver automation** in Python, with dry runs, safety checks and an audit log

Next: Google Workspace SSO and SCIM provisioning, Okta group rules, Terraform.
Details in [phase1-identity/](phase1-identity/).

## Phases

| Phase | Focus | Status |
|---|---|---|
| [1. Identity](phase1-identity/) | Okta SSO (SAML + OIDC), SCIM provisioning, JML automation, Terraform | In progress |
| [2. Endpoint security](phase2-endpoint/) | Intune, Autopilot, Conditional Access, Defender | Not started |
| [3. macOS](phase3-macos/) | Jamf Pro, FileVault, patching, smart groups | Not started |
| [4. Compliance](phase4-compliance/) | SOC 2-style controls, evidence automation, vendor evaluation | Not started |

## Safety
- Secrets go only in `.env`, which is gitignored. See `.env.example`.
- Blur org URLs, tenant IDs, emails, QR codes and tokens in screenshots.
- Commits are signed with an SSH key that lives on a YubiKey, so each one needs the key plugged in and touched.
