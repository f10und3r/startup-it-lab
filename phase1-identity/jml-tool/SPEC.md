# JML Tool — Spec

A command-line tool that handles joiners, movers and leavers for Tallow Peak in Okta.
Okta is the source of truth for access: the tool changes users and group memberships,
and group rules plus SCIM provisioning decide which apps each person gets.

## Join
What happens when someone is hired?
- Create the Okta user with first name, last name, title and department.
  Login and email are `first.last@tallowpeak-lab.com`.
- Add them to their department group (`Engineering`, `Sales`, `Ops` or `Leadership`) and to `All-Staff`.
- Apps follow from the groups: `All-Staff` gets Google Workspace, `Sales` gets Salesforce.
  The tool never assigns apps directly.
- Activate the account so Okta emails the new hire a setup link.
  The tool never sets or sees a password.
- Refuse if the login already exists or the department isn't one of the four groups.

## Move
What happens when someone changes departments?
- Remove them from their old department group, then add them to the new one.
- Update `department` (and `title`, if given) on their Okta profile.
- Leave `All-Staff` alone.
- Apps change on their own: for example, moving out of `Sales` removes Salesforce through SCIM.
- Refuse if the user doesn't exist, isn't active, or is already in that department.

## Leave
What happens when someone leaves, and in what order?
Order matters: cut live access first, then remove standing access.
1. Clear all Okta sessions and revoke OAuth tokens, so anything they're signed in to stops working right away.
2. Remove them from every group except `Everyone`. SCIM then suspends their Google Workspace
   account and removes their other app assignments.
3. Deactivate the Okta user, so they can't sign in again.
4. Record which groups they were in, so the leave can be reviewed or undone.
- Never delete the user. A deactivated account keeps the history for audits.
- Ask for confirmation (type the login back) unless `--yes` is passed.
- Target: done within 1 hour of the request (matches the Phase 4 offboarding control).

## Audit log
What does each entry record? (who, what, when, result...)
One JSON line per action in `audit/jml-YYYY-MM.jsonl` (gitignored, never pushed):
- `timestamp`: UTC, ISO 8601
- `operator`: who ran the tool (the local username)
- `action`: `join`, `move` or `leave`
- `target`: the user's login
- `changes`: groups added or removed and profile fields changed, with before and after values
- `dry_run`: true or false
- `result`: `success` or `failed`, plus the Okta error message on failure
- Every step is written to the log as it happens, so a half-finished leave shows exactly where it stopped.

## Inputs
How is the tool run? (CLI arguments, CSV file...)
```
python jml.py join  --first Alex --last Rivera --dept Engineering --title "Software Engineer"
python jml.py move  --user alex.rivera@tallowpeak-lab.com --dept Sales [--title "..."]
python jml.py leave --user alex.rivera@tallowpeak-lab.com [--yes]
```
- `--dry-run` on any command prints what would change and changes nothing.
- Reads `OKTA_ORG_URL` and `OKTA_API_TOKEN` from `.env`. The token is never printed or logged.
- Exits non-zero on any failure, so it could be scripted later.

## Out of scope
- Setting or resetting passwords, and MFA enrollment (the user does this from the activation email)
- Deleting users
- Wiping or collecting devices (Phase 2 and 3 cover devices)
- Connecting to an HR system, or manager approval steps
- Batch runs from a CSV file (possible stretch goal)
- Any app that isn't driven by Okta groups

## Open questions
- Should a leaver's Google Drive files be transferred to their manager before suspension?
- Should `move` keep the old department's access for a grace period, or cut it immediately?
