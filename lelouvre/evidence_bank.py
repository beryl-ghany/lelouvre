"""Evidence bank — source of truth for tailored application content (PRD v0.5)."""
from __future__ import annotations

import json
import re
from uuid import uuid4

from .demo import DEMO_ENTRIES, DEMO_SCREENING, is_demo, demo_profile
from .store import Problem, now

# A fresh real workspace has no candidate claims or approved screening answers.
# Fictional sample evidence is seeded only when demo mode is explicitly enabled.
DEFAULT_ENTRIES = []
DEFAULT_SCREENING = []

DEFAULT_VOICE = {
    "samples": ["Direct, specific, and modest — lead with what I built and measured."],
    "banned_phrases": ["passionate", "synergy", "rockstar", "ninja", "guru"],
    "rules": ["No invented metrics.", "One concrete result per bullet.", "Avoid generic openers."],
}

DEFAULT_TARGET = {
    "tracks": ["software engineering", "cloud security", "cybersecurity", "research"],
    "season": "Summer 2027",
    "location_policy": "United States outside South Carolina; coasts preferred",
    "remote_preference": "unknown",
    "paid_only": False,
    "relocation_limit": "",
    "dream_companies": ["Cloudflare", "Datadog"],
}


class EvidenceBank:
    def __init__(self, store):
        self.store = store
        with store.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS evidence_entries (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    organization TEXT NOT NULL DEFAULT '',
                    tools TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NOT NULL DEFAULT '',
                    results TEXT NOT NULL DEFAULT '[]',
                    links TEXT NOT NULL DEFAULT '[]',
                    variant_tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_skills (
                    skill TEXT PRIMARY KEY,
                    proficiency TEXT NOT NULL DEFAULT 'working',
                    evidence_ids TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS screening_answers (
                    id TEXT PRIMARY KEY,
                    question_shape TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK(mode IN ('auto_ok','always_ask'))
                );
                CREATE TABLE IF NOT EXISTS evidence_meta (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    voice_json TEXT NOT NULL DEFAULT '{}',
                    target_json TEXT NOT NULL DEFAULT '{}',
                    master_resume_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO evidence_meta(id, voice_json, target_json, master_resume_json, updated_at)
                VALUES (1, '{}', '{}', '{}', '');
            """)
            count = connection.execute("SELECT COUNT(*) FROM evidence_entries").fetchone()[0]
            if count == 0:
                self._seed(connection)

    def _seed(self, connection):
        timestamp = now()
        entries = DEMO_ENTRIES if is_demo() else DEFAULT_ENTRIES
        screening = DEMO_SCREENING if is_demo() else DEFAULT_SCREENING
        for entry in entries:
            eid = entry.get("id") or uuid4().hex
            connection.execute(
                """INSERT INTO evidence_entries
                   (id,kind,title,organization,tools,summary,results,links,variant_tags,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid,
                    entry["kind"],
                    entry["title"],
                    entry["organization"],
                    json.dumps(entry["tools"]),
                    entry["summary"],
                    json.dumps(entry["results"]),
                    json.dumps(entry["links"]),
                    json.dumps(entry["variant_tags"]),
                    timestamp,
                    timestamp,
                ),
            )
        for row in screening:
            connection.execute(
                "INSERT INTO screening_answers VALUES (?,?,?,?)",
                (uuid4().hex, row["question_shape"], row["answer"], row["mode"]),
            )
        connection.execute(
            "UPDATE evidence_meta SET voice_json=?, target_json=?, master_resume_json=?, updated_at=? WHERE id=1",
            (
                json.dumps(DEFAULT_VOICE),
                json.dumps(DEFAULT_TARGET),
                json.dumps(self._build_master_from_entries(connection)),
                timestamp,
            ),
        )
        skill_map = {}
        for row in connection.execute("SELECT id, tools FROM evidence_entries"):
            for tool in json.loads(row["tools"]):
                skill_map.setdefault(tool, []).append(row["id"])
        for skill, ids in skill_map.items():
            connection.execute(
                "INSERT OR REPLACE INTO evidence_skills VALUES (?,?,?)",
                (skill, "working", json.dumps(ids)),
            )

    def _build_master_from_entries(self, connection):
        sections = []
        for row in connection.execute("SELECT * FROM evidence_entries ORDER BY kind, title"):
            entry = self._entry_row(row)
            for result in entry["results"] or [entry["summary"]]:
                sections.append(
                    {
                        "id": uuid4().hex,
                        "text": f"{entry['title']}: {result}",
                        "evidence_id": entry["id"],
                        "section": entry["kind"],
                    }
                )
        # Demo identity never inherits the developer's personal resume header.
        # For real workspaces, retain a locally stored header when rebuilding.
        row = connection.execute("SELECT master_resume_json FROM evidence_meta WHERE id=1").fetchone()
        previous = json.loads(row[0] or "{}") if row else {}
        profile = demo_profile() if is_demo() else previous
        return {
            "name": profile.get("name", ""),
            "headline": "Fictional demonstration profile" if is_demo() else previous.get("headline", ""),
            "bullets": sections,
            "variant": "master",
            "version": 1,
        }

    @staticmethod
    def _entry_row(row):
        data = dict(row)
        for key in ("tools", "results", "links", "variant_tags"):
            data[key] = json.loads(data[key] or "[]")
        return data

    def snapshot(self):
        with self.store.connect() as connection:
            entries = [self._entry_row(r) for r in connection.execute("SELECT * FROM evidence_entries ORDER BY title")]
            skills = [
                {"skill": row["skill"], "proficiency": row["proficiency"], "evidence_ids": json.loads(row["evidence_ids"])}
                for row in connection.execute("SELECT * FROM evidence_skills ORDER BY skill")
            ]
            screening = [dict(r) for r in connection.execute("SELECT * FROM screening_answers ORDER BY question_shape")]
            meta = dict(connection.execute("SELECT * FROM evidence_meta WHERE id=1").fetchone())
        return {
            "entries": entries,
            "skills": skills,
            "screening_answers": screening,
            "voice": json.loads(meta["voice_json"] or "{}"),
            "target": json.loads(meta["target_json"] or "{}"),
            "master_resume": json.loads(meta["master_resume_json"] or "{}"),
            "updated_at": meta["updated_at"],
        }

    def upsert_entry(self, data):
        eid = data.get("id") or uuid4().hex
        title = str(data.get("title", "")).strip()
        if not title:
            raise Problem("Project or role title is required.")
        timestamp = now()
        tools = data.get("tools") or []
        results = data.get("results") or []
        if not isinstance(tools, list) or not isinstance(results, list):
            raise Problem("Tools and results must be lists.")
        with self.store.connect() as connection:
            existing = connection.execute("SELECT id FROM evidence_entries WHERE id=?", (eid,)).fetchone()
            payload = (
                data.get("kind", "project"),
                title,
                str(data.get("organization", "")).strip(),
                json.dumps(tools),
                str(data.get("summary", "")).strip()[:4000],
                json.dumps([str(x)[:500] for x in results]),
                json.dumps(data.get("links") or []),
                json.dumps(data.get("variant_tags") or ["swe"]),
                timestamp,
            )
            if existing:
                connection.execute(
                    """UPDATE evidence_entries SET kind=?,title=?,organization=?,tools=?,summary=?,results=?,links=?,variant_tags=?,updated_at=?
                       WHERE id=?""",
                    (*payload, eid),
                )
            else:
                connection.execute(
                    """INSERT INTO evidence_entries
                       (id,kind,title,organization,tools,summary,results,links,variant_tags,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (eid, *payload, timestamp),
                )
            connection.execute(
                "UPDATE evidence_meta SET master_resume_json=?, updated_at=? WHERE id=1",
                (json.dumps(self._build_master_from_entries(connection)), timestamp),
            )
        return self.entry(eid)

    def entry(self, entry_id):
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM evidence_entries WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise Problem("Evidence entry not found.", 404, "not_found")
        return self._entry_row(row)

    def match_screening(self, label):
        label_cf = label.casefold()
        with self.store.connect() as connection:
            for row in connection.execute("SELECT * FROM screening_answers"):
                shape = row["question_shape"].casefold()
                if shape in label_cf or label_cf in shape:
                    return dict(row)
        return None


def pick_variant(title, description):
    text = f"{title} {description}".casefold()
    if re.search(r"security|cyber|cloud|infosec", text):
        return "security"
    if re.search(r"research|ml|ai|scientist", text):
        return "research"
    return "swe"
