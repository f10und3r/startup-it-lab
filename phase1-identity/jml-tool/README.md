# JML tool

A command-line tool that onboards, moves and offboards Tallow Peak staff in Okta.
It changes users and group memberships only; Okta group rules and SCIM decide which
apps each person gets. The design is in [SPEC.md](SPEC.md).

## Setup

```bash
cd phase1-identity/jml-tool
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

It reads `OKTA_ORG_URL` and `OKTA_API_TOKEN` from the repo's `.env` (see `.env.example`).
The token is never printed or logged.

## Usage

Every command takes `--dry-run`, which shows what would change and changes nothing.

```bash
# Joiner: create the user, add them to their department and All-Staff, email a setup link
python jml.py join --first Test --last Hire --dept Sales --title "Account Executive"

# Mover: swap department groups and update the profile; All-Staff stays
python jml.py move --user test.hire@tallowpeak-lab.com --dept Ops --title "IT Support"

# Leaver: asks you to type the login back, then runs the steps below in order
python jml.py leave --user test.hire@tallowpeak-lab.com
```

Example output:

```
[LIVE] leave test.hire@tallowpeak-lab.com
  done   end all sessions and revoke OAuth tokens
  done   remove from group Ops
  done   remove from group all-staff
  done   deactivate the Okta account
```

## How leave works

The order is the point: cut live access first, then standing access.

1. **End sessions and revoke OAuth tokens.** Anything they're signed in to stops working now.
2. **Remove every Okta group.** With SCIM on, this suspends them in Google Workspace and removes other apps.
3. **Deactivate the account.** They can't sign in again. The account is kept, never deleted, for audits.

Before step 1 the tool logs the user's groups, so a leave can be reviewed or undone even if it stops halfway.

## Safety checks

The tool refuses, changes nothing and exits with code 1 when:

- `join`: the login already exists, or the department isn't Engineering, Sales, Ops or Leadership
- `move`: the user doesn't exist, is deactivated or suspended, or is already in that department
- `leave`: the user doesn't exist, is already deactivated, the confirmation doesn't match,
  or the target is the admin account that owns the API token

If Okta returns an error partway through, the tool stops and says so. The audit log shows
exactly which steps finished.

## Audit log

Each step is written to `audit/jml-YYYY-MM.jsonl` as soon as it finishes. The folder is
gitignored because it holds names and emails. A sample entry:

```json
{"timestamp": "2026-11-24T15:00:13+00:00", "operator": "f", "action": "move",
 "target": "test.hire@tallowpeak-lab.com", "step": "update_profile",
 "changes": {"before": {"department": "Sales", "title": "Account Executive"},
             "after": {"department": "Ops", "title": "IT Support"}},
 "dry_run": false, "result": "success"}
```

`result` is `success`, `failed` (with Okta's error), `refused` (a safety check), or
`planned` (a dry run).

## Files

| File | What it does |
|---|---|
| `jml.py` | The three commands and the safety checks |
| `okta.py` | The Okta API calls the tool uses |
| `audit.py` | Writes the audit log |
| `seed_users.py` | Creates the 9 fictional Tallow Peak staff |
