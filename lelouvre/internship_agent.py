"""End-to-end internship agent: discover → auto-save matches → prepare → gated apply."""
from __future__ import annotations

import json
import threading
from uuid import uuid4

from .store import Problem, now


class InternshipAgent:
    def __init__(self, store, scout_agent, apply_orchestrator):
        self.store = store
        self.scout = scout_agent
        self.apply = apply_orchestrator
        self.lock = threading.Lock()
        with store.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS internship_agent_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    auto_save INTEGER NOT NULL DEFAULT 1,
                    auto_apply INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO internship_agent_settings(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS internship_agent_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    saved INTEGER NOT NULL DEFAULT 0,
                    prepared INTEGER NOT NULL DEFAULT 0,
                    executed INTEGER NOT NULL DEFAULT 0,
                    detail TEXT NOT NULL DEFAULT '{}'
                );
            """)

    def status(self):
        with self.store.connect() as connection:
            settings = dict(connection.execute("SELECT * FROM internship_agent_settings WHERE id=1").fetchone())
            runs = [dict(r) for r in connection.execute(
                "SELECT * FROM internship_agent_runs ORDER BY started_at DESC LIMIT 8"
            )]
        for run in runs:
            run["detail"] = json.loads(run["detail"])
        scout = self.scout.repository.status()
        apply_status = self.apply.status()
        return {
            "enabled": bool(settings["enabled"]),
            "auto_save": bool(settings["auto_save"]),
            "auto_apply": bool(settings["auto_apply"]),
            "scout_enabled": scout["enabled"],
            "can_submit_employers": bool(
                set(apply_status["execution_hosts"]) - {"127.0.0.1", "localhost"}
            ),
            "browser_apply": apply_status["browser_available"],
            "runs": runs,
            "message": "Discover runs first, then saves verified Summer 2027 matches, prepares packets, and applies only when all gates pass.",
        }

    def settings(self, data):
        with self.store.connect() as connection:
            if "enabled" in data:
                if not isinstance(data["enabled"], bool):
                    raise Problem("enabled must be true or false.")
                connection.execute("UPDATE internship_agent_settings SET enabled=? WHERE id=1", (int(data["enabled"]),))
            if "auto_save" in data:
                if not isinstance(data["auto_save"], bool):
                    raise Problem("auto_save must be true or false.")
                connection.execute("UPDATE internship_agent_settings SET auto_save=? WHERE id=1", (int(data["auto_save"]),))
            if "auto_apply" in data:
                if not isinstance(data["auto_apply"], bool):
                    raise Problem("auto_apply must be true or false.")
                connection.execute("UPDATE internship_agent_settings SET auto_apply=? WHERE id=1", (int(data["auto_apply"]),))
        if data.get("enabled"):
            self.scout.repository.settings({"enabled": True})
        return self.status()

    def start(self):
        if not self.lock.acquire(blocking=False):
            raise Problem("Internship agent is already running.", 409, "run_active")
        run_id = uuid4().hex
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO internship_agent_runs(id,status,started_at) VALUES(?,?,?)",
                (run_id, "running", now()),
            )
        thread = threading.Thread(target=self._run, args=(run_id,), daemon=True, name="lelouvre-internship-agent")
        thread.start()
        return {"id": run_id, "status": "running"}

    def _run(self, run_id):
        detail = {"steps": []}
        saved = prepared = executed = 0
        try:
            with self.store.connect() as connection:
                cfg = dict(connection.execute("SELECT * FROM internship_agent_settings WHERE id=1").fetchone())
            detail["steps"].append("discover")
            scout_result = self.scout.start("internship_agent")
            if not self.scout.lock.acquire(timeout=240):
                raise Problem("Discover check timed out.", 504, "scout_timeout")
            self.scout.lock.release()
            detail["scout_run_id"] = scout_result["id"]

            if cfg["auto_save"]:
                saved = self._auto_save_matches()
                detail["steps"].append(f"auto_saved:{saved}")

            self.apply.settings(
                {
                    "auto_prepare": True,
                    "auto_execute": bool(cfg["auto_apply"]),
                    "browser_submit": bool(cfg["auto_apply"] and self.apply.status()["browser_available"]),
                }
            )
            detail["steps"].append("prepare_apply")
            pipeline = self.apply.start("autopilot")
            if not self.apply.lock.acquire(timeout=300):
                raise Problem("Prepare/apply pipeline timed out.", 504, "pipeline_timeout")
            self.apply.lock.release()
            with self.store.connect() as connection:
                row = connection.execute(
                    "SELECT prepared,executed,errors FROM apply_pipeline_runs WHERE id=?",
                    (pipeline["id"],),
                ).fetchone()
            if row:
                prepared, executed = row["prepared"], row["executed"]
                detail["pipeline"] = {
                    "id": pipeline["id"],
                    "errors": json.loads(row["errors"]) if row["errors"] else [],
                }

            status = "completed"
            with self.store.connect() as connection:
                connection.execute(
                    """UPDATE internship_agent_runs SET status=?,finished_at=?,discovered=?,saved=?,prepared=?,executed=?,detail=?
                       WHERE id=?""",
                    (status, now(), 0, saved, prepared, executed, json.dumps(detail), run_id),
                )
        except Problem as error:
            detail["error"] = {"code": error.code, "message": error.message}
            with self.store.connect() as connection:
                connection.execute(
                    "UPDATE internship_agent_runs SET status=?,finished_at=?,detail=? WHERE id=?",
                    ("failed", now(), json.dumps(detail), run_id),
                )
        except Exception as error:
            detail["error"] = {"code": "agent_error", "message": str(error)[:200]}
            with self.store.connect() as connection:
                connection.execute(
                    "UPDATE internship_agent_runs SET status=?,finished_at=?,detail=? WHERE id=?",
                    ("failed", now(), json.dumps(detail), run_id),
                )
        finally:
            self.lock.release()

    def _auto_save_matches(self):
        with self.store.connect() as connection:
            rows = connection.execute(
                """SELECT id FROM opportunities
                   WHERE disposition='new' AND type='internship' AND kind='listing'
                   AND json_extract(evaluation,'$.target')='potential_match'
                   AND (json_extract(evaluation,'$.verification')='verified_ats'
                        OR url LIKE '%greenhouse.io%' OR url LIKE '%jobs.lever.co%')"""
            ).fetchall()
            count = 0
            for row in rows:
                connection.execute(
                    "UPDATE opportunities SET disposition='saved' WHERE id=?",
                    (row["id"],),
                )
                count += 1
        return count

    def start_scheduler(self):
        def loop():
            import time
            while True:
                time.sleep(60)
                try:
                    with self.store.connect() as connection:
                        enabled = bool(connection.execute(
                            "SELECT enabled FROM internship_agent_settings WHERE id=1"
                        ).fetchone()[0])
                    if not enabled:
                        continue
                    scout_status = self.scout.repository.status()
                    last = scout_status["last_completed"]
                    due = not last or (
                        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                        - __import__("datetime").datetime.fromisoformat(last)
                    ).total_seconds() >= 6 * 3600
                    if due:
                        self.start()
                except Problem:
                    pass
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True, name="lelouvre-internship-scheduler").start()
