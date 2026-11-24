# Tallow Peak intranet (OIDC)

A small Flask web app that staff sign in to with Okta using OpenID Connect (OIDC).
It's the OIDC half of Phase 1; Salesforce and Google Workspace cover SAML.
It runs locally only, at `http://localhost:8080`.

## What it does

- **Sign in with Okta**: no passwords in the app. Okta handles the password and MFA.
- **Home page**: the signed-in person's name, email and groups.
- **Department pages**: shown only to members of Engineering, Sales, Ops or Leadership.
- **What Okta sent**: the verified ID token's claims, to show exactly what the app learned.
- **Sign out**: ends both the app session and the Okta session.

## How sign-in works

Authorization code flow with PKCE, the standard for server-side web apps:

1. **`/login`** sends the browser to Okta's `/authorize` endpoint with the app's client ID,
   the redirect URI, the scopes (`openid profile email groups`), and a PKCE challenge.
2. **The person signs in at Okta.** The app never sees their password.
3. **Okta redirects back** to `/authorization-code/callback` with a one-time code.
4. **The app swaps the code for tokens** at Okta's `/token` endpoint, server to server,
   using the client secret and the PKCE verifier. A stolen code is useless without both.
5. **The ID token is verified**: signature (against Okta's published keys), issuer,
   audience (this app's client ID), expiry and nonce. Only then is the person signed in.

| OIDC | SAML equivalent | Here |
|---|---|---|
| ID token (signed JSON) | Assertion (signed XML) | Says who signed in |
| `iss` | Issuer | The Okta org |
| `aud` | Audience | This app's client ID |
| `sub` | NameID | The person's permanent Okta ID |
| Redirect URI | ACS / Recipient URL | `/authorization-code/callback` |

## Setup

1. In Okta: **Applications** → **Create App Integration** → **OIDC** → **Web Application**.
   - Sign-in redirect URI: `http://localhost:8080/authorization-code/callback`
   - Sign-out redirect URI: `http://localhost:8080/`
   - Optional: Sign On → OpenID Connect ID Token → Groups claim filter `groups` matches regex `.*`
   - Assign it to the people or groups who should use it.
2. Add to the repo's `.env` (see `.env.example`):
   ```
   OIDC_CLIENT_ID=...
   OIDC_CLIENT_SECRET=...
   ```
3. Install and run:
   ```bash
   cd phase1-identity/intranet
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python app.py
   ```
4. Open `http://localhost:8080` (use `localhost`, not `127.0.0.1`, so the session cookie matches the redirect URI).

## Security notes

- The client secret lives only in `.env`, which is gitignored.
- The app listens on `127.0.0.1` only, so nothing on the network can reach it.
- The session cookie is signed, HTTP-only and SameSite=Lax. Restarting the app signs everyone out.
- Access is controlled in Okta by assignment: unassigned users are refused at Okta, before reaching the app.
