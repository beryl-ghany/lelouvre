"""Persistent candidate facts; saving changes invalidates packet approval."""
import json
from pathlib import Path

from .demo import demo_profile, is_demo
from .store import Problem

DEFAULT_PROFILE = dict.fromkeys(("name", "first_name", "last_name", "school", "graduation", "gpa", "email", "phone", "resume_path", "work_authorized", "requires_sponsorship"), "")


class ProfileStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS candidate_profile (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")

    def get(self):
        with self.store.connect() as c:
            row = c.execute("SELECT data FROM candidate_profile WHERE id=1").fetchone()
        base = demo_profile() if is_demo() else DEFAULT_PROFILE
        return {**base, **(json.loads(row[0]) if row else {})}

    def save(self, data):
        profile = self.get()
        for key in DEFAULT_PROFILE:
            if key in data:
                if not isinstance(data[key], str):
                    raise Problem(f"{key} must be text.")
                profile[key] = data[key].strip()[:2000]
        if profile["email"] and ("@" not in profile["email"] or any(x.isspace() for x in profile["email"])):
            raise Problem("Enter a valid email address.")
        path = profile.get("resume_path")
        if path and (not Path(path).is_file() or Path(path).suffix.lower() not in (".pdf", ".docx")):
            raise Problem("Resume must be the full path to an existing PDF or DOCX file.")
        if path and Path(path).stat().st_size > 10 * 1024 * 1024:
            raise Problem("Resume must be smaller than 10 MB.")
        with self.store.connect() as c:
            c.execute("INSERT OR REPLACE INTO candidate_profile VALUES(1,?)", (json.dumps(profile),))
            # Facts and attachments may have changed since a packet was approved.
            c.execute("UPDATE application_runs SET packet=json_set(packet,'$.approved',json('false')) WHERE status NOT IN ('submitted','submitting','receipt_unconfirmed')")
        return profile
