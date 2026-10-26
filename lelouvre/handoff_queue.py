"""Persist handoffs for Today (demo form runs, etc.)."""
from __future__ import annotations

import json
from uuid import uuid4

from .store import now


class HandoffQueue:
    def __init__(self, store):
        self.store = store
        with store.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS handoff_queue (
                    id TEXT PRIMARY KEY,
                    organization TEXT NOT NULL,
                    title TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def push(self, organization, title, handoff, *, url=""):
        payload = dict(handoff)
        if url:
            payload["url"] = url
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO handoff_queue VALUES (?,?,?,?,?)",
                (uuid4().hex, organization, title, json.dumps(payload), now()),
            )

    def list_recent(self, limit=10):
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM handoff_queue ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload"])
            items.append(
                {
                    "organization": row["organization"],
                    "title": row["title"],
                    "next_step": payload.get("what_to_do") or payload.get("headline", ""),
                    "message": payload.get("message", ""),
                    "url": payload.get("url", ""),
                    "outcome": payload.get("outcome", "needs_you"),
                }
            )
        return items
