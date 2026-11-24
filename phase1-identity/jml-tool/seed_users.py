"""Seed the fictional Tallow Peak staff into Okta.

Dry run by default: prints what it would do and changes nothing.
    python seed_users.py             # dry run
    python seed_users.py --apply     # create users and add them to groups
    python seed_users.py --apply --activate   # also send activation emails

Safe to re-run: users that already exist are skipped, and group
memberships that already exist are left alone.
Reads OKTA_ORG_URL and OKTA_API_TOKEN from the repo's .env.
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

DOMAIN = "tallowpeak-lab.com"
ALL_STAFF = "All-Staff"

# Fictional people only.
STAFF = [
    ("Alex", "Rivera", "Engineering", "Senior Software Engineer"),
    ("Priya", "Nair", "Engineering", "Software Engineer"),
    ("Marcus", "Bell", "Engineering", "DevOps Engineer"),
    ("Hana", "Kobayashi", "Engineering", "Engineering Manager"),
    ("Jordan", "Price", "Sales", "Account Executive"),
    ("Sofia", "Marquez", "Sales", "Sales Development Rep"),
    ("Theo", "Grant", "Ops", "IT Operations Lead"),
    ("Sam", "Okafor", "Leadership", "CEO"),
    ("Elena", "Varga", "Leadership", "CTO"),
]


def okta_session():
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    base = os.environ.get("OKTA_ORG_URL", "").rstrip("/")
    token = os.environ.get("OKTA_API_TOKEN", "")
    if not base or not token:
        sys.exit("OKTA_ORG_URL and OKTA_API_TOKEN must be set in .env")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"SSWS {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s, base


def check(r):
    if not r.ok:
        try:
            detail = r.json().get("errorCauses") or r.json().get("errorSummary")
        except ValueError:
            detail = r.text
        sys.exit(f"Okta API error {r.status_code}: {detail}")
    return r


def load_groups(s, base):
    groups = check(s.get(f"{base}/api/v1/groups", params={"limit": 200})).json()
    return {g["profile"]["name"].lower(): g for g in groups}


def find_user(s, base, login):
    r = s.get(f"{base}/api/v1/users/{requests.utils.quote(login)}")
    if r.status_code == 404:
        return None
    return check(r).json()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true", help="make changes (default: dry run)")
    p.add_argument("--activate", action="store_true", help="send activation emails to new users")
    args = p.parse_args()

    s, base = okta_session()
    groups = load_groups(s, base)
    needed = {dept for _, _, dept, _ in STAFF} | {ALL_STAFF}
    missing = sorted(n for n in needed if n.lower() not in groups)
    if missing:
        sys.exit(f"Create these groups in Okta first: {', '.join(missing)}")

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] {len(STAFF)} users at @{DOMAIN}\n")

    for first, last, dept, title in STAFF:
        login = f"{first.lower()}.{last.lower()}@{DOMAIN}"
        user = find_user(s, base, login)
        label = f"{login:<34} {dept:<12} {title}"

        if user and user["status"] == "STAGED" and args.activate:
            if args.apply:
                check(s.post(f"{base}/api/v1/users/{user['id']}/lifecycle/activate",
                             params={"sendEmail": "true"}))
            print(f"  activate {label}")
        elif user:
            print(f"  exists   {label}  ({user['status'].lower()})")
        elif not args.apply:
            print(f"  create   {label}")
        else:
            body = {"profile": {
                "firstName": first, "lastName": last,
                "email": login, "login": login,
                "department": dept, "title": title,
                "organization": "Tallow Peak",
            }}
            r = s.post(f"{base}/api/v1/users",
                       params={"activate": str(args.activate).lower()}, json=body)
            user = check(r).json()
            print(f"  created  {label}")

        for gname in (dept, ALL_STAFF):
            if user and args.apply:
                gid = groups[gname.lower()]["id"]
                check(s.put(f"{base}/api/v1/groups/{gid}/users/{user['id']}"))

    if not args.apply:
        print("\nNothing changed. Re-run with --apply to create them.")
    elif not args.activate:
        print("\nUsers are staged (not activated). Re-run with --apply --activate,"
              " or activate them in the Admin Console, when you're ready.")


if __name__ == "__main__":
    main()
