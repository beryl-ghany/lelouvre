"""SQLite storage, validation, and transactional application history."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

STAGES = {
    "internship": (
        "Saved",
        "Preparing",
        "Ready",
        "Applied",
        "Assessment",
        "Interview",
        "Offer",
        "Accepted",
        "Rejected",
        "Withdrawn",
        "Closed",
    ),
    "scholarship": ("Submitted", "Under review", "Shortlisted", "Awarded", "Not selected", "Withdrawn"),
}


class Problem(Exception):
    def __init__(self, message, status=400, code="invalid_input", **details):
        self.message, self.status, self.code, self.details = message, status, code, details
        super().__init__(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def normalized(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[\u2010-\u2015]", "-", value).split())


def text(data, key, maximum=2000, required=False):
    value = data.get(key, "")
    if not isinstance(value, str):
        raise Problem(f"{key.replace('_', ' ').capitalize()} must be text.")
    value = value.strip()
    if required and not value:
        raise Problem(f"{key.replace('_', ' ').capitalize()} is required.")
    if len(value) > maximum:
        raise Problem(f"{key.replace('_', ' ').capitalize()} is too long (maximum {maximum}).")
    return value


def date_value(data, key):
    value = text(data, key, 10)
    if value:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise Problem(f"{key.replace('_', ' ').capitalize()} must be a valid YYYY-MM-DD date.")
    return value or None


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES (1);
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL CHECK(type IN ('internship','scholarship')),
                    organization TEXT NOT NULL, title TEXT NOT NULL, cycle TEXT NOT NULL,
                    organization_key TEXT NOT NULL, title_key TEXT NOT NULL, cycle_key TEXT NOT NULL,
                    stage TEXT NOT NULL, submitted_date TEXT, url TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT 'user_reported',
                    origin TEXT NOT NULL DEFAULT 'manual', revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(type, organization_key, title_key, cycle_key)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
                    kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_application ON events(application_id, created_at);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, application_id TEXT REFERENCES applications(id),
                    title TEXT NOT NULL, due_date TEXT, priority TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open', revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY, payload TEXT NOT NULL, application_id TEXT NOT NULL REFERENCES applications(id)
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def event(connection, application_id, kind, payload):
        connection.execute("INSERT INTO events VALUES (?,?,?,?,?)", (
            uuid4().hex, application_id, kind, json.dumps(payload, ensure_ascii=False), now()
        ))

    @staticmethod
    def row(connection, application_id):
        found = connection.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        if found is None:
            raise Problem("Application not found.", 404, "not_found")
        return dict(found)

    def application(self, application_id):
        with self.connect() as connection:
            result = self.row(connection, application_id)
            result["events"] = [
                {**dict(row), "payload": json.loads(row["payload"])}
                for row in connection.execute("SELECT * FROM events WHERE application_id=? ORDER BY rowid", (application_id,))
            ]
            result["tasks"] = [dict(row) for row in connection.execute(
                "SELECT * FROM tasks WHERE application_id=? ORDER BY created_at DESC", (application_id,)
            )]
            return result

    def applications(self, scope="all"):
        if scope not in ("all", *STAGES):
            raise Problem("Unknown opportunity scope.")
        with self.connect() as connection:
            query, parameters = "SELECT * FROM applications", ()
            if scope != "all":
                query += " WHERE type=?"
                parameters = (scope,)
            return [dict(row) for row in connection.execute(query + " ORDER BY updated_at DESC, id", parameters)]

    def create(self, data, key):
        kind = text(data, "type", 20, True)
        if kind not in STAGES:
            raise Problem("Choose internship or scholarship.")
        organization, title = text(data, "organization", 160, True), text(data, "title", 200, True)
        cycle = text(data, "cycle", 60)
        stage = text(data, "stage", 30, True)
        if stage not in STAGES[kind]:
            raise Problem("That stage does not belong to this opportunity type.")
        submitted = date_value(data, "submitted_date")
        url, location = text(data, "url", 2000), text(data, "location", 200)
        if url:
            from urllib.parse import urlsplit
            try:
                parsed = urlsplit(url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError
            except ValueError:
                raise Problem("Use a valid http or https job/program link without credentials.")
        note = text(data, "note", 4000)
        payload = json.dumps({"type": kind, "organization": organization, "title": title, "cycle": cycle,
                              "stage": stage, "submitted_date": submitted, "url": url, "location": location,
                              "note": note}, sort_keys=True)
        keys = normalized(organization), normalized(title), normalized(cycle)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT * FROM idempotency WHERE key=?", (key,)).fetchone()
            if old:
                if old["payload"] != payload:
                    raise Problem("This save key was already used with different details. Review and save again.", 409, "key_conflict")
                return self.row(connection, old["application_id"]), False
            duplicates = [dict(row) for row in connection.execute("""
                SELECT * FROM applications WHERE type=? AND organization_key=? AND title_key=?
                AND (cycle_key=? OR cycle_key='' OR ?='')
            """, (kind, keys[0], keys[1], keys[2], keys[2]))]
            if duplicates:
                raise Problem("A matching or possibly matching application already exists. Open it to review.",
                              409, "possible_duplicate", matches=duplicates)
            application_id, timestamp = uuid4().hex, now()
            connection.execute("""INSERT INTO applications
                (id,type,organization,title,cycle,organization_key,title_key,cycle_key,stage,submitted_date,url,location,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    application_id, kind, organization, title, cycle, *keys, stage, submitted, url, location, timestamp, timestamp
                ))
            self.event(connection, application_id, "created", {"stage": stage, "submitted_date": submitted,
                       "origin": "manual", "evidence": "user_reported", "note": note})
            connection.execute("INSERT INTO idempotency VALUES (?,?,?)", (key, payload, application_id))
            return self.row(connection, application_id), True

    def update(self, application_id, data):
        revision = data.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise Problem("The current record revision is required.")
        submitted, reason = date_value(data, "submitted_date"), text(data, "reason", 2000, True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self.row(connection, application_id)
            if revision != current["revision"]:
                raise Problem("This record changed in another window. Reload it before updating.", 409, "stale_revision")
            stage = text(data, "stage", 30, True)
            if stage not in STAGES[current["type"]]:
                raise Problem("That stage does not belong to this opportunity type.")
            if stage == current["stage"] and submitted == current["submitted_date"]:
                return current
            connection.execute("UPDATE applications SET stage=?,submitted_date=?,revision=revision+1,updated_at=? WHERE id=?",
                               (stage, submitted, now(), application_id))
            self.event(connection, application_id, "updated", {
                "before": {"stage": current["stage"], "submitted_date": current["submitted_date"]},
                "after": {"stage": stage, "submitted_date": submitted}, "reason": reason,
            })
            return self.row(connection, application_id)

    def note(self, application_id, data):
        note = text(data, "note", 4000, True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.row(connection, application_id)
            self.event(connection, application_id, "note", {"text": note})
            connection.execute("UPDATE applications SET revision=revision+1,updated_at=? WHERE id=?", (now(), application_id))

    def tasks(self):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("""
                SELECT tasks.*,applications.type,applications.organization,applications.title AS application_title
                FROM tasks LEFT JOIN applications ON tasks.application_id=applications.id
                ORDER BY CASE tasks.status WHEN 'open' THEN 0 ELSE 1 END,
                CASE tasks.due_date IS NULL WHEN 1 THEN 1 ELSE 0 END,tasks.due_date,tasks.created_at
            """)]

    def create_task(self, data):
        title = text(data, "title", 200, True)
        due = date_value(data, "due_date")
        priority = text(data, "priority", 20, True)
        if priority not in ("urgent", "review", "info", "neutral"):
            raise Problem("Unknown task priority.")
        application_id = text(data, "application_id", 40) or None
        task_id = uuid4().hex
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if application_id:
                self.row(connection, application_id)
            connection.execute("INSERT INTO tasks(id,application_id,title,due_date,priority,created_at) VALUES (?,?,?,?,?,?)",
                               (task_id, application_id, title, due, priority, now()))
            if application_id:
                self.event(connection, application_id, "task_created", {"task_id": task_id, "title": title, "due_date": due})
        return {"id": task_id}

    def resolve_task(self, task_id):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise Problem("Task not found.", 404, "not_found")
            if task["status"] == "resolved":
                return
            connection.execute("UPDATE tasks SET status='resolved',resolved_at=?,revision=revision+1 WHERE id=?", (now(), task_id))
            if task["application_id"]:
                self.event(connection, task["application_id"], "task_resolved", {"task_id": task_id, "title": task["title"]})
