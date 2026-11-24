"""Audit log: one JSON line per step, written the moment the step finishes.

Files go to audit/jml-YYYY-MM.jsonl next to this script. The audit/ folder is
gitignored because it holds real names and emails, so it never reaches GitHub.
"""

import getpass
import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parent / "audit"


class AuditLog:
    def __init__(self, action, target, dry_run):
        self.action = action
        self.target = target
        self.dry_run = dry_run
        self.operator = getpass.getuser()

    def record(self, step, changes=None, result="success", error=None):
        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(timespec="seconds"),
            "operator": self.operator,
            "action": self.action,
            "target": self.target,
            "step": step,
            "changes": changes or {},
            "dry_run": self.dry_run,
            "result": result,
        }
        if error:
            entry["error"] = str(error)
        AUDIT_DIR.mkdir(exist_ok=True)
        path = AUDIT_DIR / f"jml-{now:%Y-%m}.jsonl"
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
