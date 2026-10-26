"""High-accuracy apply pipeline: verify → prepare → optional browser execute."""
from __future__ import annotations

import json
import hashlib
import threading
from uuid import uuid4

from .application_agent import ApplicationAgent, active_profile
from .browser_executor import BrowserExecutor
from .policy import auto_execute_blockers
from .store import Problem, Store, normalized, now
from .verify import best_apply_url, classify_apply_url


class ApplyOrchestrator:
    def __init__(self, store: Store, application_agent: ApplicationAgent | None = None):
        self.store = store
        self.application_agent = application_agent or ApplicationAgent(store)
        self.lock = threading.Lock()
        with store.connect() as connection:
            try:
                connection.execute(
                    "ALTER TABLE apply_orchestrator_settings ADD COLUMN apply_mode TEXT NOT NULL DEFAULT 'ask'"
                )
            except Exception:
                pass
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS apply_orchestrator_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    auto_prepare INTEGER NOT NULL DEFAULT 0,
                    auto_execute INTEGER NOT NULL DEFAULT 0,
                    browser_submit INTEGER NOT NULL DEFAULT 0,
                    apply_mode TEXT NOT NULL DEFAULT 'ask'
                );
                INSERT OR IGNORE INTO apply_orchestrator_settings(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS apply_pipeline_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    prepared INTEGER NOT NULL DEFAULT 0,
                    executed INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    errors TEXT NOT NULL DEFAULT '[]'
                );
            """)

    def status(self):
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM apply_orchestrator_settings WHERE id=1").fetchone()
            settings = dict(row) if row else {}
            settings.setdefault("apply_mode", "ask")
            runs = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM apply_pipeline_runs ORDER BY started_at DESC LIMIT 10"
                )
            ]
            queued = connection.execute(
                """SELECT COUNT(*) FROM opportunities
                   WHERE disposition='saved' AND kind IN ('listing','lead')
                   AND json_extract(evaluation,'$.target') IN ('potential_match','needs_review')"""
            ).fetchone()[0]
        for run in runs:
            run["errors"] = json.loads(run["errors"])
        apply_mode = settings.get("apply_mode") or "ask"
        return {
            "auto_prepare": bool(settings["auto_prepare"]),
            "auto_execute": bool(settings["auto_execute"]),
            "browser_submit": bool(settings["browser_submit"]),
            "apply_mode": apply_mode if apply_mode in ("ask", "auto_when_safe") else "ask",
            "browser_available": BrowserExecutor(active_profile()).available(),
            "queued_saved": queued,
            "runs": runs,
            "execution_hosts": sorted(self.application_agent.execution_hosts),
            "policy": "Deterministic gates; LLM analysis is advisory only.",
        }

    def settings(self, data):
        with self.store.connect() as connection:
            if "auto_prepare" in data:
                if not isinstance(data["auto_prepare"], bool):
                    raise Problem("auto_prepare must be true or false.")
                connection.execute(
                    "UPDATE apply_orchestrator_settings SET auto_prepare=? WHERE id=1",
                    (int(data["auto_prepare"]),),
                )
            if "auto_execute" in data:
                if not isinstance(data["auto_execute"], bool):
                    raise Problem("auto_execute must be true or false.")
                connection.execute(
                    "UPDATE apply_orchestrator_settings SET auto_execute=? WHERE id=1",
                    (int(data["auto_execute"]),),
                )
            if "browser_submit" in data:
                if not isinstance(data["browser_submit"], bool):
                    raise Problem("browser_submit must be true or false.")
                connection.execute(
                    "UPDATE apply_orchestrator_settings SET browser_submit=? WHERE id=1",
                    (int(data["browser_submit"]),),
                )
            if "apply_mode" in data:
                mode = data["apply_mode"]
                if mode not in ("ask", "auto_when_safe"):
                    raise Problem("apply_mode must be ask or auto_when_safe.")
                connection.execute(
                    "UPDATE apply_orchestrator_settings SET apply_mode=? WHERE id=1",
                    (mode,),
                )
        return self.status()

    def start(self, trigger="manual", opportunity_id=None):
        if not self.lock.acquire(blocking=False):
            raise Problem("An apply pipeline run is already in progress.", 409, "run_active")
        run_id = uuid4().hex
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO apply_pipeline_runs(id,status,trigger,started_at) VALUES(?,?,?,?)",
                (run_id, "running", trigger, now()),
            )
        thread = threading.Thread(
            target=self._run,
            args=(run_id, opportunity_id, trigger),
            daemon=True,
            name="lelouvre-apply-orchestrator",
        )
        thread.start()
        return {"id": run_id, "status": "running"}

    def prepare_opportunity(self, opportunity_id):
        row = self._resolve_row(self._opportunity(opportunity_id))
        evaluation = json.loads(row["evaluation"]) if isinstance(row["evaluation"], str) else row["evaluation"]
        existing = self._existing_application(row, evaluation)
        if existing:
            raise Problem(
                "An application for this role is already tracked.",
                409,
                "already_applied",
                application_id=existing["id"],
            )
        return self._prepare_row(row)

    def _existing_application(self, row, evaluation):
        cycle = "Summer 2027" if evaluation.get("season") == "confirmed" else ""
        org_key = normalized(row["organization"])
        title_key = normalized(row["title"])
        cycle_key = normalized(cycle) if cycle else None
        with self.store.connect() as connection:
            for app in connection.execute("SELECT * FROM applications WHERE type='internship'"):
                app = dict(app)
                if normalized(app["organization"]) != org_key or normalized(app["title"]) != title_key:
                    continue
                if cycle_key and normalized(app["cycle"] or "") and normalized(app["cycle"]) != cycle_key:
                    continue
                return app
        return None

    def _run(self, run_id, opportunity_id, trigger="manual"):
        resolved = prepared = executed = skipped = attempted = 0
        errors = []
        try:
            settings = self.status()
            rows = [self._opportunity(opportunity_id)] if opportunity_id else self._saved_candidates()
            for row in rows:
                try:
                    row = self._resolve_row(row)
                    if row.get("_resolved"):
                        resolved += 1
                    evaluation = json.loads(row["evaluation"]) if isinstance(row["evaluation"], str) else row["evaluation"]
                    if row["kind"] == "lead" and evaluation.get("verification") != "verified_ats":
                        skipped += 1
                        continue
                    if evaluation.get("target") == "excluded":
                        skipped += 1
                        continue
                    if (
                        opportunity_id is None
                        and not settings["auto_prepare"]
                        and trigger not in ("autopilot", "internship_agent", "manual")
                    ):
                        skipped += 1
                        continue
                    existing = self._existing_application(row, evaluation)
                    if existing:
                        skipped += 1
                        errors.append(
                            {
                                "opportunity_id": row.get("id"),
                                "code": "already_applied",
                                "message": f"Application already tracked for {existing['organization']} · {existing['title']}.",
                            }
                        )
                        continue
                    run = self._reviewed_run(row)
                    if run is None:
                        run = self._prepare_row(row)
                    run = self.application_agent.enrich_run(run)
                    prepared += 1
                    if run["policy"]["decision"] != "approved":
                        skipped += 1
                        continue
                    auto_submit = settings.get("apply_mode") == "auto_when_safe" and settings["auto_execute"]
                    if not auto_submit and settings.get("apply_mode", "ask") == "ask":
                        continue
                    if not settings["auto_execute"]:
                        continue
                    if not run["packet"].get("approved"):
                        skipped += 1
                        continue
                    from .scout import evaluate

                    refreshed = evaluate(row["title"], row["location"], row["description"]) or evaluation
                    blockers = auto_execute_blockers(run["packet"], refreshed)
                    if blockers:
                        skipped += 1
                        errors.append(
                            {
                                "opportunity_id": row.get("id"),
                                "code": "accuracy_gate",
                                "message": blockers[0],
                                "blockers": blockers,
                            }
                        )
                        continue
                    if attempted >= 5:
                        skipped += 1
                        continue
                    result = self.application_agent.execute(run["id"], auto_submit=True, browser=settings["browser_submit"])
                    if (result.get("receipt") or {}).get("submitted"):
                        attempted += 1
                    if result["status"] == "submitted" and (result.get("receipt") or {}).get("confirmed"):
                        executed += 1
                    else:
                        skipped += 1
                        errors.append({"opportunity_id": row["id"], "code": "not_submitted", "message": ((result.get("receipt") or {}).get("evidence") or (result.get("handoff") or {}).get("message") or "Application needs review.")})
                except Problem as error:
                    errors.append({"opportunity_id": row.get("id"), "code": error.code, "message": error.message})
                except Exception as error:
                    errors.append({"opportunity_id": row.get("id"), "code": "pipeline_error", "message": str(error)[:200]})
            status = "completed_with_errors" if errors else "completed"
            with self.store.connect() as connection:
                connection.execute(
                    """UPDATE apply_pipeline_runs SET status=?,finished_at=?,resolved=?,prepared=?,executed=?,skipped=?,errors=?
                       WHERE id=?""",
                    (status, now(), resolved, prepared, executed, skipped, json.dumps(errors), run_id),
                )
        except Exception as error:
            with self.store.connect() as connection:
                connection.execute(
                    """UPDATE apply_pipeline_runs SET status='failed',finished_at=?,errors=? WHERE id=?""",
                    (now(), json.dumps([{"code": "fatal", "message": str(error)[:200]}]), run_id),
                )
        finally:
            self.lock.release()

    def _saved_candidates(self):
        with self.store.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM opportunities WHERE disposition='saved'
                   ORDER BY json_extract(evaluation,'$.priority') DESC, last_seen DESC LIMIT 25"""
            ).fetchall()
        return [dict(row) for row in rows]

    def _opportunity(self, opportunity_id):
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
        if row is None:
            raise Problem("Opportunity not found.", 404, "not_found")
        return dict(row)

    def _resolve_row(self, row):
        evaluation = json.loads(row["evaluation"])
        if row["kind"] != "lead" and classify_apply_url(row["url"] or ""):
            return row
        preferred = row["url"]
        if row.get("source_id") == "datadog" and str(row.get("external_id", "")).isdigit():
            preferred = "https://job-boards.greenhouse.io/datadog/jobs/" + str(row["external_id"])
        apply_url, verified = best_apply_url(row["description"], preferred=preferred)
        if not verified:
            return row
        evaluation = dict(evaluation)
        evaluation["verification"] = verified["confidence"]
        evaluation["apply_platform"] = verified["platform"]
        blockers = [b for b in evaluation.get("blockers", []) if "Community post" not in b]
        evaluation["blockers"] = blockers
        with self.store.connect() as connection:
            connection.execute(
                """UPDATE opportunities SET url=?,kind='listing',evaluation=?,last_change='verified'
                   WHERE id=?""",
                (apply_url, json.dumps(evaluation), row["id"]),
            )
        updated = dict(row)
        updated["url"] = apply_url
        updated["kind"] = "listing"
        updated["evaluation"] = json.dumps(evaluation)
        updated["_resolved"] = True
        return updated

    def _prepare_row(self, row):
        from .scout import evaluate

        evaluation = json.loads(row["evaluation"]) if isinstance(row["evaluation"], str) else row["evaluation"]
        refreshed = evaluate(row["title"], row["location"], row["description"])
        if refreshed is None:
            raise Problem("Opportunity no longer matches internship discovery rules.", 409, "not_eligible")
        if refreshed["target"] == "excluded":
            raise Problem("Opportunity is outside target scope.", 409, "excluded")
        destination = row["url"]
        if not classify_apply_url(destination):
            raise Problem("Apply URL is not verified.", 409, "destination_unverified")
        fields = []
        try:
            inspected = self.application_agent.inspect(destination)
            fields = inspected.get("fields", [])
        except Exception as error:
            raise Problem("Could not inspect the application. Check browser support or open the employer form.", 409, "unfamiliar_form") from error
        if not fields:
            raise Problem("No application fields were found.", 409, "unfamiliar_form")
        listing = {
            "title": row["title"],
            "location": row["location"],
            "description": row["description"][:8000],
            "organization": row["organization"],
        }
        cycle = "Summer 2027" if refreshed.get("season") == "confirmed" else "Unknown season"
        run = self.application_agent.prepare(
            {
                "destination": destination,
                "fields": fields,
                "listing": listing,
                "evaluation": refreshed,
                "opportunity_id": row["id"],
                "application": {
                    "organization": row["organization"],
                    "title": row["title"],
                    "cycle": cycle,
                    "location": row["location"],
                },
            }
        )
        packet = run["packet"]
        packet["source_fingerprint"] = self._source_fingerprint(row)
        self.application_agent._save_packet(run["id"], packet, run["status"])
        return self.application_agent.run(run["id"])

    @staticmethod
    def _source_fingerprint(row):
        return hashlib.sha256(json.dumps([row.get(k, "") for k in ("title", "organization", "description", "location", "url")]).encode()).hexdigest()

    def _reviewed_run(self, row):
        for run in self.application_agent.list():
            packet = run["packet"]
            if run.get("opportunity_id") == row["id"] and packet.get("source_fingerprint") == self._source_fingerprint(row) and packet.get("profile_fingerprint") == self.application_agent.profile_fingerprint():
                return run
        return None

    def _browser_execute(self, run, submit, auto_submit=False):
        return self.application_agent.execute(run["id"], auto_submit=auto_submit, browser=True)
