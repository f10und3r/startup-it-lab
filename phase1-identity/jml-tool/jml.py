"""JML tool: joiners, movers and leavers for Tallow Peak in Okta.

    python jml.py join  --first Alex --last Rivera --dept Engineering --title "Software Engineer"
    python jml.py move  --user alex.rivera@tallowpeak-lab.com --dept Sales [--title "..."]
    python jml.py leave --user alex.rivera@tallowpeak-lab.com [--yes]

Add --dry-run to any command to see what would change without changing anything.
See SPEC.md for what each command does and why.
"""

import argparse
import re
import sys
import unicodedata

from audit import AuditLog
from okta import Okta, OktaError

DOMAIN = "tallowpeak-lab.com"
DEPARTMENTS = ["Engineering", "Sales", "Ops", "Leadership"]
ALL_STAFF = "All-Staff"
# Okta won't let these statuses be moved; they're already offboarded or blocked.
GONE_STATUSES = {"DEPROVISIONED", "SUSPENDED"}


class Refused(Exception):
    """The request breaks a rule in SPEC.md, so nothing was changed."""


class Run:
    """Carries out (or, in a dry run, only describes) each step, and logs it."""

    def __init__(self, action, target, dry_run):
        self.dry_run = dry_run
        self.log = AuditLog(action, target, dry_run)
        mode = "DRY RUN" if dry_run else "LIVE"
        print(f"[{mode}] {action} {target}")

    def refuse(self, reason):
        self.log.record("check", result="refused", error=reason)
        raise Refused(reason)

    def step(self, name, description, do, changes=None):
        """Run one change. The log line is written as soon as it finishes or fails."""
        if self.dry_run:
            print(f"  would  {description}")
            self.log.record(name, changes, result="planned")
            return None
        try:
            result = do()
        except OktaError as e:
            print(f"  FAILED {description}: {e}")
            self.log.record(name, changes, result="failed", error=e)
            raise
        print(f"  done   {description}")
        self.log.record(name, changes)
        return result


# --- helpers ---------------------------------------------------------------

def department(name):
    """Return the official department name, or None if it isn't one of the four."""
    for d in DEPARTMENTS:
        if d.lower() == name.strip().lower():
            return d
    return None


def make_login(first, last):
    """'José', 'De La Cruz' -> 'jose.de-la-cruz@tallowpeak-lab.com'"""
    def clean(s):
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", s.strip().lower()))
    return f"{clean(first)}.{clean(last)}@{DOMAIN}"


def group(groups, name):
    g = groups.get(name.lower())
    if not g:
        raise Refused(f"Okta has no group named {name}. Create it first.")
    return g


def dept_groups_of(okta, user):
    """The user's current department groups (normally exactly one)."""
    names = {d.lower() for d in DEPARTMENTS}
    return [g for g in okta.user_groups(user["id"]) if g["profile"]["name"].lower() in names]


# --- commands --------------------------------------------------------------

def join(okta, args):
    dept = department(args.dept)
    login = make_login(args.first, args.last)
    run = Run("join", login, args.dry_run)

    if not dept:
        run.refuse(f"Unknown department {args.dept!r}. Use one of: {', '.join(DEPARTMENTS)}")
    groups = okta.groups_by_name()
    dept_group, staff_group = group(groups, dept), group(groups, ALL_STAFF)
    if okta.get_user(login):
        run.refuse(f"{login} already exists in Okta")

    profile = {
        "firstName": args.first.strip(), "lastName": args.last.strip(),
        "login": login, "email": login,
        "department": dept, "organization": "Tallow Peak",
    }
    if args.title:
        profile["title"] = args.title

    # activate=True: Okta emails the new hire a link to set their own password and MFA.
    user = run.step("create_user", f"create and activate {login} (Okta emails a setup link)",
                    lambda: okta.create_user(profile, activate=True),
                    changes={"profile": profile})
    user_id = user["id"] if user else None

    # Groups drive app access: All-Staff -> Google Workspace, Sales -> Salesforce.
    for g in (dept_group, staff_group):
        name = g["profile"]["name"]
        run.step("add_group", f"add to group {name}",
                 lambda g=g: okta.add_to_group(g["id"], user_id),
                 changes={"groups_added": [name]})


def move(okta, args):
    dept = department(args.dept)
    run = Run("move", args.user, args.dry_run)

    if not dept:
        run.refuse(f"Unknown department {args.dept!r}. Use one of: {', '.join(DEPARTMENTS)}")
    user = okta.get_user(args.user)
    if not user:
        run.refuse(f"No Okta user {args.user}")
    if user["status"] in GONE_STATUSES:
        run.refuse(f"{args.user} is {user['status'].lower()}; only current staff can move")

    current = dept_groups_of(okta, user)
    if any(g["profile"]["name"].lower() == dept.lower() for g in current):
        run.refuse(f"{args.user} is already in {dept}")
    new_group = group(okta.groups_by_name(), dept)

    # Remove the old department first, so they never hold both at once.
    for g in current:
        name = g["profile"]["name"]
        run.step("remove_group", f"remove from group {name}",
                 lambda g=g: okta.remove_from_group(g["id"], user["id"]),
                 changes={"groups_removed": [name]})

    run.step("add_group", f"add to group {dept}",
             lambda: okta.add_to_group(new_group["id"], user["id"]),
             changes={"groups_added": [dept]})

    before = {k: user["profile"].get(k) for k in ("department", "title")}
    after = {"department": dept}
    if args.title:
        after["title"] = args.title
    run.step("update_profile", f"set profile {after}",
             lambda: okta.update_profile(user["id"], after),
             changes={"before": before, "after": after})


def leave(okta, args):
    run = Run("leave", args.user, args.dry_run)

    user = okta.get_user(args.user)
    if not user:
        run.refuse(f"No Okta user {args.user}")
    if user["status"] == "DEPROVISIONED":
        run.refuse(f"{args.user} is already deactivated")
    if user["id"] == okta.me()["id"]:
        run.refuse("That's the admin account running this tool. Refusing to offboard it.")

    # Only ordinary Okta groups can be removed. Built-in groups (Everyone, Okta
    # Administrators) and app-imported groups are managed by Okta itself.
    groups = okta.user_groups(user["id"])
    removable = [g for g in groups if g["type"] == "OKTA_GROUP"]
    names = [g["profile"]["name"] for g in removable]

    # Record the groups first, so even a leave that fails halfway can be undone.
    run.log.record("snapshot", {"status_before": user["status"], "groups_before": names})

    if not args.dry_run and not args.yes:
        print(f"\nThis will sign {args.user} out everywhere, remove them from "
              f"{', '.join(names) or 'no groups'}, and deactivate them.")
        if input("Type their login to confirm: ").strip().lower() != args.user.lower():
            run.refuse("Confirmation didn't match")

    # 1. Cut live access first: every session and token stops working now.
    run.step("clear_sessions", "end all sessions and revoke OAuth tokens",
             lambda: okta.clear_sessions(user["id"]))

    # 2. Remove standing access. With SCIM, this suspends them in Google Workspace.
    for g in removable:
        name = g["profile"]["name"]
        run.step("remove_group", f"remove from group {name}",
                 lambda g=g: okta.remove_from_group(g["id"], user["id"]),
                 changes={"groups_removed": [name]})

    # 3. Block sign-in for good. The account is kept (never deleted) for audits.
    run.step("deactivate", "deactivate the Okta account",
             lambda: okta.deactivate(user["id"]),
             changes={"status": {"before": user["status"], "after": "DEPROVISIONED"}})


# --- command line ----------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Joiners, movers and leavers for Tallow Peak in Okta.")
    sub = p.add_subparsers(dest="command", required=True)

    j = sub.add_parser("join", help="onboard a new hire")
    j.add_argument("--first", required=True)
    j.add_argument("--last", required=True)
    j.add_argument("--dept", required=True, help=", ".join(DEPARTMENTS))
    j.add_argument("--title")

    m = sub.add_parser("move", help="change someone's department")
    m.add_argument("--user", required=True, help="their login, e.g. alex.rivera@" + DOMAIN)
    m.add_argument("--dept", required=True, help=", ".join(DEPARTMENTS))
    m.add_argument("--title")

    lv = sub.add_parser("leave", help="offboard someone")
    lv.add_argument("--user", required=True, help="their login")
    lv.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    for s in (j, m, lv):
        s.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    commands = {"join": join, "move": move, "leave": leave}
    try:
        commands[args.command](Okta(), args)
    except Refused as e:
        print(f"  REFUSED {e}\nNothing was changed.", file=sys.stderr)
        return 1
    except OktaError as e:
        print(f"\nStopped: {e}\nSteps before this one were completed. "
              "See the audit log for exactly what changed.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    if args.dry_run:
        print("Dry run: nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
