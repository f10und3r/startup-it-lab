# JML tool

A joiner/mover/leaver automation tool for Okta. It will be built from [SPEC.md](SPEC.md) in Phase 1, weekend 2.

Setup:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
It reads `OKTA_ORG_URL` and `OKTA_API_TOKEN` from the repo's `.env`.
