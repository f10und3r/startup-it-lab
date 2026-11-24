# Startup IT Lab

A home lab for practicing IT work at a startup. The fictional company is **Northwind**.

> This is lab work. Nothing here is a production environment.

| Phase | Focus | Status |
|---|---|---|
| [1. Identity](phase1-identity/) | Okta SSO (SAML + OIDC), SCIM provisioning, JML automation, Terraform | Not started |
| [2. Endpoint security](phase2-endpoint/) | Intune, Autopilot, Conditional Access, Defender | Not started |
| [3. macOS](phase3-macos/) | Jamf Pro, FileVault, patching, smart groups | Not started |
| [4. Compliance](phase4-compliance/) | SOC 2-style controls, evidence automation, vendor evaluation | Not started |

## Safety
- Secrets go only in `.env`, which is gitignored. See `.env.example`.
- Blur org URLs, tenant IDs, emails, QR codes and tokens in screenshots.
