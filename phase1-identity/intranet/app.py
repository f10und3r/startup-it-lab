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

On top of sign-in (authentication), the app decides what each person may see (authorization):
- Department pages need membership of that Okta group, or they return 403.
- The payroll page needs a fresh MFA sign-in (step-up), or it sends you back to Okta.
"""

import os
import secrets
import time
from functools import wraps
from pathlib import Path

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template_string, request, session, url_for

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ISSUER = os.environ.get("OKTA_ORG_URL", "").rstrip("/")
CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
if not (ISSUER and CLIENT_ID and CLIENT_SECRET):
    raise SystemExit("Set OKTA_ORG_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET in .env")

PORT = 8080
BASE_URL = f"http://localhost:{PORT}"
CALLBACK = f"{BASE_URL}/authorization-code/callback"
STEP_UP_MAX_AGE = 5 * 60  # payroll needs an MFA sign-in from the last 5 minutes

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

# Department pages: the Okta group that may see each one, and fictional content.
DEPARTMENTS = {
    "engineering": {"group": "Engineering", "title": "Engineering",
                    "items": ["On-call rota", "Deploy runbook", "Architecture notes"]},
    "sales": {"group": "Sales", "title": "Sales",
              "items": ["Pipeline review", "Pricing sheet", "Demo accounts"]},
    "ops": {"group": "Ops", "title": "Operations",
            "items": ["IT requests", "Vendor list", "Onboarding checklist"]},
    "leadership": {"group": "Leadership", "title": "Leadership",
                   "items": ["Board deck", "Hiring plan", "Budget"]},
}

# Fictional payroll figures for the step-up demo.
PAYROLL = [("Engineering", 4, "$612,000"), ("Sales", 2, "$268,000"),
           ("Ops", 1, "$96,000"), ("Leadership", 2, "$410,000")]


# --- helpers ---------------------------------------------------------------

def page(body_template, status=200, **context):
    """Render the body (values auto-escaped), then place it in the page frame."""
    context.setdefault("user", session.get("user"))
    body = render_template_string(body_template, **context)
    return render_template_string(PAGE, body=body, **context), status


def in_group(name):
    return name.lower() in {g.lower() for g in session["user"]["groups"]}


# acr values where Okta vouches that the sign-in used two or more factors.
# A YubiKey/passkey with its PIN counts (possession + knowledge) even though
# Okta's amr for it is just ["pop"], so the decision uses acr, not amr.
STRONG_ACR = {"urn:okta:loa:2fa:any", "phr", "phrh"}


def mfa_age():
    """Seconds since the person last signed in with MFA, or None if they didn't use MFA."""
    claims = session.get("claims", {})
    strong = claims.get("acr") in STRONG_ACR or "mfa" in claims.get("amr", [])
    if not strong or "auth_time" not in claims:
        return None
    return int(time.time()) - int(claims["auth_time"])


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            session["next"] = request.path  # come back here after signing in
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapper


# --- sign-in and sign-out --------------------------------------------------

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("home"))
    return page(SIGNED_OUT)


@app.route("/login")
def login():
    return okta.authorize_redirect(CALLBACK)


@app.route("/step-up")
@login_required
def step_up():
    """Send the person back to Okta to sign in again with MFA, then return to payroll."""
    session["next"] = url_for("payroll")
    session["step_up_pending"] = True
    # max_age=0: don't reuse the existing Okta session, authenticate again now.
    # acr_values: ask Okta for a two-factor sign-in.
    return okta.authorize_redirect(CALLBACK, max_age=0, acr_values="urn:okta:loa:2fa:any")


@app.route("/authorization-code/callback")
def callback():
    # Okta sends ?error=... instead of a code when sign-in is refused or cancelled.
    if "error" in request.args:
        return sign_in_error(request.args.get("error"), request.args.get("error_description"))
    try:
        # Swaps the code for tokens and verifies the ID token's signature, issuer,
        # audience, expiry and nonce. If any check fails, this raises.
        token = okta.authorize_access_token()
    except OAuthError as e:
        return sign_in_error(e.error, e.description)
    except Exception as e:  # e.g. a stale or reused callback link: the state no longer matches
        return sign_in_error("sign_in_failed", str(e))

    claims = token["userinfo"]
    session["user"] = {
        "name": claims.get("name"),
        "email": claims.get("email"),
        "groups": claims.get("groups", []),
        "groups_sent": "groups" in claims,
    }
    session["claims"] = {k: claims[k] for k in
                         ("iss", "aud", "sub", "email", "name", "groups", "iat", "exp", "auth_time", "amr", "acr")
                         if k in claims}
    session["id_token"] = token.get("id_token")
    if session.pop("step_up_pending", False):
        session["step_up_returned"] = True
        age = int(time.time()) - int(claims["auth_time"]) if "auth_time" in claims else None
        print(f"[step-up] amr={claims.get('amr')} acr={claims.get('acr')} "
              f"auth_time_age={age}s", flush=True)
    return redirect(session.pop("next", None) or url_for("home"))


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


# --- pages -----------------------------------------------------------------

@app.route("/home")
@login_required
def home():
    depts = [(slug, d["title"], in_group(d["group"])) for slug, d in DEPARTMENTS.items()]
    return page(SIGNED_IN, depts=depts, claims=session.get("claims", {}))


@app.route("/dept/<slug>")
@login_required
def department(slug):
    dept = DEPARTMENTS.get(slug)
    if not dept:
        abort(404)
    if not in_group(dept["group"]):
        # Authorization: signed in, but not allowed. Checked on the server, so
        # typing the URL directly doesn't get around it.
        return page(FORBIDDEN, status=403, needed=dept["group"])
    return page(DEPARTMENT, dept=dept)


@app.route("/payroll")
@login_required
def payroll():
    age = mfa_age()
    if age is None or age > STEP_UP_MAX_AGE:
        # Just came back from Okta and still not good enough: explain instead of looping.
        just_tried = session.pop("step_up_returned", False)
        return page(STEP_UP, age=age, limit=STEP_UP_MAX_AGE // 60, just_tried=just_tried,
                    claims=session.get("claims", {}), now=int(time.time()))
    session.pop("step_up_returned", None)
    claims = session["claims"]
    return page(PAYROLL_PAGE, rows=PAYROLL, age=age, amr=claims.get("amr", []), acr=claims.get("acr"))


# --- error pages -----------------------------------------------------------

FRIENDLY_ERRORS = {
    "access_denied": ("You don't have access to the intranet",
                      "Your Okta account isn't assigned to this app, or you cancelled sign-in. "
                      "Ask IT to add you to the All-Staff group."),
    "login_required": ("Your Okta session has ended", "Sign in again to continue."),
    "unmet_authentication_requirements": ("Extra verification needed",
                                          "Okta couldn't complete the MFA this page needs. "
                                          "Check your security key or Okta Verify and try again."),
    "mismatching_state": ("That sign-in link has expired",
                          "Sign-in links work once and only in the tab that started them. Start again."),
}


def sign_in_error(code, detail):
    title, advice = FRIENDLY_ERRORS.get(
        code, ("Sign-in didn't work", "Something went wrong between the intranet and Okta. Try again."))
    session.pop("next", None)
    return page(ERROR, status=401, title=title, advice=advice, code=code, detail=detail)


@app.errorhandler(404)
def not_found(_):
    return page(ERROR, status=404, title="Page not found",
                advice="That page doesn't exist on the intranet.", code="404", detail=None)


@app.errorhandler(500)
def server_error(_):
    return page(ERROR, status=500, title="Something broke",
                advice="The intranet hit an error. Try again in a moment.", code="500", detail=None)


# --- templates -------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tallow Peak Intranet</title>
<style>
  :root { --ink:#1d2433; --quiet:#5b6475; --line:#dfe3ea; --accent:#2f6f5e; --bg:#f6f7f9; --card:#fff;
          --warn:#8a5a00; --warn-bg:#fdf6e7; --bad:#a3302a; --bad-bg:#fcefee; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 system-ui,-apple-system,sans-serif; color:var(--ink); background:var(--bg); }
  header { background:var(--accent); color:#fff; padding:14px 24px; display:flex; justify-content:space-between; align-items:center; gap:16px; }
  header a { color:#fff; }
  header nav a { margin-left:16px; }
  main { max-width:760px; margin:32px auto; padding:0 16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px 24px; margin-bottom:16px; }
  .card.warn { background:var(--warn-bg); border-color:#ecd9a8; }
  .card.bad { background:var(--bad-bg); border-color:#f0c9c6; }
  .btn { display:inline-block; background:var(--accent); color:#fff; padding:10px 18px; border-radius:8px; text-decoration:none; font-weight:600; }
  .quiet { color:var(--quiet); }
  .chip { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 10px; margin:2px 4px 2px 0; font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; }
  .tile { display:block; border:1px solid var(--line); border-radius:8px; padding:12px 14px; text-decoration:none; color:var(--ink); }
  .tile.locked { color:var(--quiet); background:var(--bg); }
  .tile small { display:block; color:var(--quiet); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  td, th { border-top:1px solid var(--line); padding:6px 4px; vertical-align:top; text-align:left; word-break:break-all; }
  code { font-size:13px; }
</style></head>
<body><header><strong>Tallow Peak Intranet</strong>
{% if user %}<nav><a href="/home">Home</a><a href="/payroll">Payroll</a><a href="/logout">Sign out</a></nav>{% endif %}</header>
<main>{{ body | safe }}</main></body></html>"""

SIGNED_OUT = """<div class="card"><h1>Welcome to Tallow Peak</h1>
<p class="quiet">Staff sign in with their Tallow Peak Okta account.</p>
<a class="btn" href="/login">Sign in with Okta</a></div>"""

SIGNED_IN = """
<div class="card"><h1>Hi, {{ user.name }}</h1>
<p class="quiet">{{ user.email }}</p>
{% for g in user.groups %}<span class="chip">{{ g }}</span>{% endfor %}
{% if not user.groups_sent %}<p class="quiet">Okta didn't send a groups claim, so department access can't be checked.
Turn on the groups claim for this app in Okta.</p>{% endif %}</div>

<div class="card"><h2>Company news</h2><p>Everyone in All-Staff sees this. Q4 all-hands is on the calendar.</p></div>

<div class="card"><h2>Departments</h2>
<p class="quiet">Pages open to members of that Okta group. Locked ones return 403.</p>
<div class="grid">{% for slug, title, allowed in depts %}
<a class="tile {{ '' if allowed else 'locked' }}" href="/dept/{{ slug }}">{{ title }}
<small>{{ 'Open' if allowed else 'Locked' }}</small></a>{% endfor %}</div></div>

<div class="card"><h2>Payroll</h2>
<p class="quiet">Sensitive. Needs an MFA sign-in from the last few minutes.</p>
<a class="btn" href="/payroll">Open payroll</a></div>

<div class="card"><h2>What Okta sent</h2>
<p class="quiet">Claims from the verified ID token. This is how the app knows who you are.</p>
<table>{% for k, v in claims.items() %}<tr><td>{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}</table></div>
"""

DEPARTMENT = """<div class="card"><h1>{{ dept.title }}</h1>
<p class="quiet">Visible to the {{ dept.group }} group.</p>
<ul>{% for item in dept["items"] %}<li>{{ item }}</li>{% endfor %}</ul>
<a href="/home">Back to home</a></div>"""

FORBIDDEN = """<div class="card bad"><h1>403: Access denied</h1>
<p>You're signed in, but this page is only for members of the <strong>{{ needed }}</strong> group.</p>
<p class="quiet">Access comes from your Okta groups. If you've moved teams, IT updates your groups
and the change applies the next time you sign in.</p>
<a href="/home">Back to home</a></div>"""

STEP_UP = """<div class="card warn"><h1>Verify it's you</h1>
<p>Payroll needs an MFA sign-in from the last {{ limit }} minutes.</p>
<p class="quiet">{% if age is none %}Your current sign-in didn't include MFA.
{% else %}Your last MFA sign-in was {{ (age // 60) }} minutes ago.{% endif %}</p>
{% if just_tried %}<p><strong>You just verified, but Okta's answer still didn't meet the rule.</strong>
Okta returned <code>acr</code> = {{ claims.get('acr') }}, <code>amr</code> = {{ claims.get('amr') }} and a sign-in time
{% if claims.get('auth_time') %}{{ ((now - claims['auth_time']) // 60) }} minutes ago{% else %}(none){% endif %}.</p>
<p class="quiet">The page needs a two-factor acr (or <code>mfa</code> in amr) and a sign-in time under {{ limit }} minutes.</p>
{% endif %}
<a class="btn" href="/step-up">Verify with Okta</a></div>"""

PAYROLL_PAGE = """<div class="card"><h1>Payroll</h1>
<p class="quiet">Verified {{ age }} seconds ago. acr: <code>{{ acr }}</code>, amr: <code>{{ amr | join(', ') }}</code>. Fictional figures.</p>
<table><tr><th>Department</th><th>Headcount</th><th>Annual payroll</th></tr>
{% for d, n, total in rows %}<tr><td>{{ d }}</td><td>{{ n }}</td><td>{{ total }}</td></tr>{% endfor %}</table></div>"""

ERROR = """<div class="card bad"><h1>{{ title }}</h1><p>{{ advice }}</p>
{% if code %}<p class="quiet">Code: <code>{{ code }}</code>{% if detail %} ({{ detail }}){% endif %}</p>{% endif %}
<a class="btn" href="/">Start again</a></div>"""


if __name__ == "__main__":
    # Local only: listens on this Mac, not the network.
    app.run(host="127.0.0.1", port=PORT, debug=False)
