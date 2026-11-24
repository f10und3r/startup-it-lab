"""A small Okta API client: only the calls the JML tool needs.

Reads OKTA_ORG_URL and OKTA_API_TOKEN from the repo's .env.
The token is sent in a header and never printed or logged.
"""

import os
import time
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv


class OktaError(Exception):
    """An Okta API call failed. The message is Okta's own error text."""

    def __init__(self, status, message):
        super().__init__(f"Okta API error {status}: {message}")
        self.status = status


class Okta:
    def __init__(self):
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        self.base = os.environ.get("OKTA_ORG_URL", "").rstrip("/")
        token = os.environ.get("OKTA_API_TOKEN", "")
        if not self.base or not token:
            raise OktaError("config", "OKTA_ORG_URL and OKTA_API_TOKEN must be set in .env")
        self.http = requests.Session()
        self.http.headers.update({
            "Authorization": f"SSWS {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    # --- low level ---------------------------------------------------------

    def _call(self, method, path, **kwargs):
        """Send one request. Waits and retries once if Okta's rate limit is hit."""
        for attempt in range(2):
            r = self.http.request(method, self.base + path, timeout=30, **kwargs)
            if r.status_code == 429 and attempt == 0:
                reset = int(r.headers.get("X-Rate-Limit-Reset", time.time() + 5))
                time.sleep(max(1, reset - time.time()))
                continue
            break
        if not r.ok:
            try:
                body = r.json()
                causes = [c.get("errorSummary") for c in body.get("errorCauses", [])]
                message = "; ".join(filter(None, causes)) or body.get("errorSummary")
            except ValueError:
                message = r.text[:200]
            raise OktaError(r.status_code, message)
        return r.json() if r.content else None

    # --- users -------------------------------------------------------------

    def get_user(self, login):
        """Return the user, or None if no user has that login."""
        try:
            return self._call("GET", f"/api/v1/users/{quote(login)}")
        except OktaError as e:
            if e.status == 404:
                return None
            raise

    def me(self):
        """The user that owns the API token (the admin running this tool)."""
        return self._call("GET", "/api/v1/users/me")

    def create_user(self, profile, activate):
        return self._call("POST", "/api/v1/users",
                          params={"activate": str(activate).lower()},
                          json={"profile": profile})

    def update_profile(self, user_id, fields):
        """Partial update: only the given profile fields change."""
        return self._call("POST", f"/api/v1/users/{user_id}", json={"profile": fields})

    def clear_sessions(self, user_id):
        """End every Okta session and revoke OAuth/OIDC tokens issued to the user."""
        self._call("DELETE", f"/api/v1/users/{user_id}/sessions",
                   params={"oauthTokens": "true"})

    def deactivate(self, user_id):
        self._call("POST", f"/api/v1/users/{user_id}/lifecycle/deactivate")

    # --- groups ------------------------------------------------------------

    def groups_by_name(self):
        """All groups, keyed by lower-case name (so All-Staff matches all-staff)."""
        groups = self._call("GET", "/api/v1/groups", params={"limit": 200})
        return {g["profile"]["name"].lower(): g for g in groups}

    def user_groups(self, user_id):
        return self._call("GET", f"/api/v1/users/{user_id}/groups")

    def add_to_group(self, group_id, user_id):
        self._call("PUT", f"/api/v1/groups/{group_id}/users/{user_id}")

    def remove_from_group(self, group_id, user_id):
        self._call("DELETE", f"/api/v1/groups/{group_id}/users/{user_id}")
