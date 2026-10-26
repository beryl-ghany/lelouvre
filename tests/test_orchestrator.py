from tests.support import seed_candidate
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lelouvre.application_agent import ApplicationAgent
from lelouvre.orchestrator import ApplyOrchestrator
from lelouvre.scout import ScoutStore
from lelouvre.store import Problem, Store

TEST_ROOT = Path(__file__).resolve().parent.parent / ".tmp"
TEST_ROOT.mkdir(exist_ok=True)


class FakeLLM:
    def analyze(self, listing):
        return {
            "role_category": "software_engineering",
            "season": "summer_2027",
            "location_status": "us_outside_south_carolina",
            "eligibility": "needs_review",
            "summary": "Structured test analysis.",
            "requirements": ["Python"],
            "review_flags": [],
            "evidence": [listing.get("title", "")],
            "provider": "test",
            "model": "test",
        }


class FormHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        body = b'<form action="/submit" method="post"><input name="full_name" required><input name="gpa" required></form>'
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.store = Store(Path(self.directory.name) / "orch.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FormHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.apply_url = f"http://127.0.0.1:{self.server.server_port}/apply"
        ScoutStore(self.store)
        self.agent = ApplicationAgent(self.store, execution_hosts={"127.0.0.1", "localhost"}, llm=FakeLLM())
        seed_candidate(self.agent)
        self.agent.inspect = lambda destination: {
            "action": self.apply_url,
            "method": "post",
            "fields": [{"name": "full_name", "required": True}, {"name": "gpa", "required": True}],
        }
        self.orchestrator = ApplyOrchestrator(self.store, self.agent)
        self.opportunity_id = self._insert_opportunity("https://boards.greenhouse.io/example/jobs/123")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def _insert_opportunity(self, url):
        evaluation = {
            "target": "potential_match",
            "season": "confirmed",
            "track": "SWE",
            "priority": 90,
            "reasons": [],
            "matched_skills": [],
            "gaps": [],
            "blockers": [],
            "eligibility": "Needs review",
            "rules_version": "rules-4-role-season-location",
            "verification": "verified_ats",
        }
        with self.store.connect() as connection:
            connection.execute(
                """INSERT INTO opportunities
                (id,source_id,external_id,type,organization,title,location,url,kind,availability,
                 first_seen,last_seen,last_checked,content_hash,description,evaluation,disposition,last_change)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "opp-1",
                    "cloudflare",
                    "123",
                    "internship",
                    "Example",
                    "Software Engineering Intern Summer 2027",
                    "New York, NY",
                    url,
                    "listing",
                    "listed",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    "hash",
                    "Python REST APIs for Summer 2027 internship.",
                    json.dumps(evaluation),
                    "saved",
                    "discovered",
                ),
            )
        return "opp-1"

    def test_prepare_saved_opportunity_creates_packet(self):
        run = self.orchestrator.prepare_opportunity(self.opportunity_id)
        self.assertIn(run["status"], ("prepared", "needs_review"))
        self.assertIsNotNone(run["packet"]["analysis"])

    def test_scheduled_pipeline_skips_batch_without_auto_prepare(self):
        result = self.orchestrator.start(trigger="scheduled")
        self.assertTrue(self.orchestrator.lock.acquire(timeout=5))
        self.orchestrator.lock.release()
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM apply_pipeline_runs WHERE id=?", (result["id"],)).fetchone()
        self.assertEqual(row["prepared"], 0)
        self.assertEqual(row["executed"], 0)

    def test_manual_run_prepares_without_enabling_automatic_submission(self):
        result = self.orchestrator.start()
        self.assertTrue(self.orchestrator.lock.acquire(timeout=5))
        self.orchestrator.lock.release()
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM apply_pipeline_runs WHERE id=?", (result["id"],)).fetchone()
        self.assertEqual(row["prepared"], 1)
        self.assertEqual(row["executed"], 0)
        self.assertFalse(self.orchestrator.status()["auto_prepare"])

    def test_lead_without_verified_url_blocks_prepare(self):
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE opportunities SET kind='lead', url='', evaluation=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "target": "needs_review",
                            "verification": "unverified_lead",
                            "blockers": ["Community post"],
                            "season": "unknown",
                            "track": "SWE",
                            "priority": 10,
                            "reasons": [],
                            "matched_skills": [],
                            "gaps": [],
                            "eligibility": "Needs review",
                            "rules_version": "rules-4-role-season-location",
                        }
                    ),
                    self.opportunity_id,
                ),
            )
        with self.assertRaises(Problem) as caught:
            self.orchestrator.prepare_opportunity(self.opportunity_id)
        self.assertEqual(caught.exception.code, "destination_unverified")

    def test_pipeline_reuses_reviewed_packet(self):
        run = self.orchestrator.prepare_opportunity(self.opportunity_id)
        self.agent.approve_packet(run["id"])
        result = self.orchestrator.start()
        self.assertTrue(self.orchestrator.lock.acquire(timeout=5))
        self.orchestrator.lock.release()
        self.assertEqual(len(self.agent.list()), 1)
        self.assertTrue(self.agent.run(run["id"])["packet"]["approved"])

    def test_changed_posting_requires_fresh_packet(self):
        run = self.orchestrator.prepare_opportunity(self.opportunity_id)
        self.agent.approve_packet(run["id"])
        row = self.orchestrator._opportunity(self.opportunity_id)
        row["description"] += " New required qualification."
        self.assertIsNone(self.orchestrator._reviewed_run(row))

    def test_failed_inspection_does_not_create_packet(self):
        def fail(_):
            raise OSError("Unavailable")
        self.agent.inspect = fail
        with self.assertRaises(Problem):
            self.orchestrator.prepare_opportunity(self.opportunity_id)
        self.assertEqual(self.agent.list(), [])

    def test_datadog_url_resolves_to_supported_ats(self):
        row = self.orchestrator._opportunity(self.opportunity_id)
        row.update(source_id="datadog", external_id="8052118", url="https://careers.datadoghq.com/detail/8052118/")
        resolved = self.orchestrator._resolve_row(row)
        self.assertEqual(resolved["url"], "https://job-boards.greenhouse.io/datadog/jobs/8052118")

    def test_auto_queue_caps_attempts_at_five_and_counts_confirmations(self):
        row = self.orchestrator._opportunity(self.opportunity_id)
        rows = [{**row, "id": f"opp-{i}"} for i in range(6)]
        packet = {"approved": True, "analysis": {"provider": "none"}}
        prepared = {"id": "reviewed", "policy": {"decision": "approved"}, "packet": packet}
        self.orchestrator.settings({"auto_execute": True, "apply_mode": "auto_when_safe"})
        with patch.object(self.orchestrator, '_saved_candidates', return_value=rows), \
             patch.object(self.orchestrator, '_existing_application', return_value=None), \
             patch.object(self.orchestrator, '_reviewed_run', return_value=prepared), \
             patch.object(self.agent, 'enrich_run', side_effect=lambda r: r), \
             patch.object(self.agent, 'execute', return_value={"status": "receipt_unconfirmed", "receipt": {"submitted": True, "confirmed": False}}) as execute:
            result = self.orchestrator.start()
            self.assertTrue(self.orchestrator.lock.acquire(timeout=5))
            self.orchestrator.lock.release()
            self.assertEqual(execute.call_count, 5)
        with self.store.connect() as c:
            pipeline = c.execute('SELECT * FROM apply_pipeline_runs WHERE id=?', (result['id'],)).fetchone()
        self.assertEqual(pipeline['executed'], 0)
        self.assertEqual(pipeline['skipped'], 6)


if __name__ == "__main__":
    unittest.main()
