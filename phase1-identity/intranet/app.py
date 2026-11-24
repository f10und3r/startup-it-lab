"""Tallow Peak intranet: a small web app you sign in to with Okta (OpenID Connect).

Run:  python app.py   then open http://localhost:8080
Reads OKTA_ORG_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET from the repo's .env.

How sign-in works (authorization code flow with PKCE):
1. /login sends the browser to Okta with this app's client ID and a one-time challenge.
2. The person signs in at Okta (password + MFA). This app never sees their password.
3. Okta redirects back to /authorization-code/callback with a short-lived code.
4. The app swaps that code (plus its client secret) for tokens, server to server.
5. The ID token says who the person is (name, email, groups). Its signature is checked
   against Okta's published keys before anything in it is trusted.
"""

import os
import secrets
from functools import wraps
from pathlib import Path

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, redirect, render_template_string, session, url_for

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ISSUER = os.environ.get("OKTA_ORG_URL", "").rstrip("/")
CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
if not (ISSUER and CLIENT_ID and CLIENT_SECRET):
    raise SystemExit("Set OKTA_ORG_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET in .env")

PORT = 8080
BASE_URL = f"http://localhost:{PORT}"

app = Flask(__name__)
# Signs the session cookie. A fresh random key each start is fine for a lab:
# restarting the app just signs everyone out.
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

oauth = OAuth(app)
okta = oauth.register(
    name="okta",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    # Okta publishes its endpoints and signing keys here; Authlib reads them.
    server_metadata_url=f"{ISSUER}/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile email groups", "code_challenge_method": "S256"},
)

# What each department sees. Fictional content for the demo.
DEPARTMENT_PAGES = {
    "Engineering": ("Engineering", "On-call rota, deploy runbook, architecture notes"),
    "Sales": ("Sales", "Pipeline review, pricing sheet, demo accounts"),
    "Ops": ("Operations", "IT requests, vendor list, onboarding checklist"),
    "Leadership": ("Leadership", "Board deck, hiring plan, budget"),
}


def page(body_template, **context):
    """Render the body (values auto-escaped), then place it in the page frame."""
    body = render_template_string(body_template, **context)
    return render_template_string(PAGE, body=body, **context)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("home"))
    return page(SIGNED_OUT)


@app.route("/login")
def login():
    return okta.authorize_redirect(f"{BASE_URL}/authorization-code/callback")


@app.route("/authorization-code/callback")
def callback():
    # Swaps the code for tokens and verifies the ID token's signature, issuer,
    # audience and expiry. If any check fails, this raises and nobody is signed in.
    token = okta.authorize_access_token()
    claims = token["userinfo"]
    session["user"] = {
        "name": claims.get("name"),
        "email": claims.get("email"),
        "groups": claims.get("groups", []),
    }
    session["claims"] = {k: claims[k] for k in
                         ("iss", "aud", "sub", "email", "name", "groups", "iat", "exp", "amr")
                         if k in claims}
    session["id_token"] = token.get("id_token")
    return redirect(url_for("home"))


@app.route("/home")
@login_required
def home():
    user = session["user"]
    groups = {g.lower() for g in user["groups"]}
    pages = [page for dept, page in DEPARTMENT_PAGES.items() if dept.lower() in groups]
    return page(SIGNED_IN, user=user, pages=pages, claims=session.get("claims", {}))


@app.route("/logout")
def logout():
    id_token = session.pop("id_token", None)
    session.clear()
    end_session = okta.load_server_metadata().get("end_session_endpoint")
    if id_token and end_session:
        # Also end the Okta session, so "sign out" really signs out.
        return redirect(f"{end_session}?id_token_hint={id_token}"
                        f"&post_logout_redirect_uri={BASE_URL}/")
    return redirect(url_for("index"))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tallow Peak Intranet</title>
<style>
  :root { --ink:#1d2433; --quiet:#5b6475; --line:#dfe3ea; --accent:#2f6f5e; --bg:#f6f7f9; --card:#fff; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 system-ui,-apple-system,sans-serif; color:var(--ink); background:var(--bg); }
  header { background:var(--accent); color:#fff; padding:14px 24px; display:flex; justify-content:space-between; align-items:center; }
  header a { color:#fff; }
  main { max-width:760px; margin:32px auto; padding:0 16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px 24px; margin-bottom:16px; }
  .btn { display:inline-block; background:var(--accent); color:#fff; padding:10px 18px; border-radius:8px; text-decoration:none; font-weight:600; }
  .quiet { color:var(--quiet); }
  .chip { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 10px; margin:2px 4px 2px 0; font-size:13px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td { border-top:1px solid var(--line); padding:6px 4px; vertical-align:top; word-break:break-all; }
  td:first-child { width:90px; color:var(--quiet); }
</style></head>
<body><header><strong>Tallow Peak Intranet</strong>{% if user %}<a href="/logout">Sign out</a>{% endif %}</header>
<main>{{ body | safe }}</main></body></html>"""

SIGNED_OUT = """<div class="card"><h1>Welcome to Tallow Peak</h1>
<p class="quiet">Staff sign in with their Tallow Peak Okta account.</p>
<a class="btn" href="/login">Sign in with Okta</a></div>"""

SIGNED_IN = """
<div class="card"><h1>Hi, {{ user.name }}</h1>
<p class="quiet">{{ user.email }}</p>
{% for g in user.groups %}<span class="chip">{{ g }}</span>{% endfor %}</div>

<div class="card"><h2>Company news</h2><p>Everyone in All-Staff sees this. Q4 all-hands is on the calendar.</p></div>

{% for title, text in pages %}
<div class="card"><h2>{{ title }}</h2><p>{{ text }}</p></div>
{% else %}
<div class="card"><p class="quiet">No department pages for your groups yet.</p></div>
{% endfor %}

<div class="card"><h2>What Okta sent</h2>
<p class="quiet">Claims from the verified ID token. This is how the app knows who you are.</p>
<table>{% for k, v in claims.items() %}<tr><td>{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}</table></div>
"""


if __name__ == "__main__":
    # Local only: listens on this Mac, not the network.
    app.run(host="127.0.0.1", port=PORT, debug=False)
