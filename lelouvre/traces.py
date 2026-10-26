"""Local agent trace log (Gemma calls, pipeline steps) for debugging and demos."""
from __future__ import annotations

import json
from uuid import uuid4

from .store import now


class TraceLog:
    def __init__(self, store):
        self.store = store
        with store.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS agent_traces (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def log(self, kind, detail):
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO agent_traces VALUES (?,?,?,?)",
                (uuid4().hex, kind, json.dumps(detail, ensure_ascii=False), now()),
            )

    def list(self, limit=40, kind=None):
        with self.store.connect() as connection:
            if kind:
                rows = connection.execute(
                    "SELECT * FROM agent_traces WHERE kind=? ORDER BY created_at DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM agent_traces ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item["detail"])
            out.append(item)
        return out
