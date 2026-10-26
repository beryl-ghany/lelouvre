from tests.support import seed_candidate
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lelouvre.application_agent import ApplicationAgent
from lelouvre.store import Problem, Store

TEST_ROOT = Path(__file__).resolve().parent.parent / ".tmp"
TEST_ROOT.mkdir(exist_ok=True)


class FormHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def do_GET(self):
        body = b'<form action="/submit" method="post"><input name="full_name" required><input name="gpa" required></form>'
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0)); self.server.received = self.rfile.read(length).decode()
        body = b'Thank you. Your application was received.'
        self.send_response(200); self.end_headers(); self.wfile.write(body)


class ApplicationAgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.store = Store(Path(self.directory.name) / "agent.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FormHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/apply"
        self.agent = ApplicationAgent(self.store)
        seed_candidate(self.agent)
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.directory.cleanup()
    def test_complete_controlled_submission_captures_receipt_and_logs(self):
        run = self.agent.prepare({"destination":self.url, "fields":[{"name":"full_name","required":True},{"name":"gpa","required":True}],
            "application":{"organization":"Example","title":"SWE Intern","cycle":"Summer 2027","location":"New York, NY"}})
        self.assertEqual(run["status"], "prepared")
        run = self.agent.approve_packet(run["id"])
        run = self.agent.execute(run["id"], auto_submit=True)
        self.assertEqual(run["status"], "submitted")
        self.assertTrue(run["receipt"]["confirmed"])
        self.assertIn("full_name=Jordan+Demo", self.server.received)
        self.assertEqual(self.store.applications()[0]["evidence"], "verified_receipt")
    def test_unknown_required_question_routes_to_review(self):
        run = self.agent.prepare({"destination":self.url,"fields":[{"name":"why_us","label":"Why us?","required":True}]})
        self.assertEqual(run["status"], "needs_review")
        result = self.agent.execute(run["id"], auto_submit=True)
        self.assertEqual(result["outcome"], "needs_you")
    def test_external_host_execution_stays_disabled(self):
        run = self.agent.prepare({"destination":"https://example.com/apply","fields":[{"name":"name"}], "application":{"organization":"Example","title":"SWE Intern","cycle":"Summer 2027"}})
        run = self.agent.approve_packet(run["id"])
        result = self.agent.execute(run["id"], auto_submit=True)
        self.assertEqual(result["handoff"]["reason_code"], "host_not_enabled")


if __name__ == "__main__": unittest.main()
