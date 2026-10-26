import concurrent.futures
import csv
import io
import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from lelouvre.server import make_server
from lelouvre.store import Problem, Store

TEST_ROOT = Path(__file__).resolve().parent.parent / ".tmp"
TEST_ROOT.mkdir(exist_ok=True)


def record(**changes):
    return {"type": "internship", "organization": "Example Employer", "title": "SWE Intern",
            "cycle": "Summer 2027", "stage": "Applied", **changes}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.path = Path(self.directory.name) / "test.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_records_survive_reopen_without_inventing_dates_or_receipts(self):
        application, created = self.store.create(record(), "first-save")
        reopened = Store(self.path).application(application["id"])
        self.assertTrue(created)
        self.assertIsNone(reopened["submitted_date"])
        self.assertEqual(reopened["evidence"], "user_reported")
        self.assertEqual(len(reopened["events"]), 1)

    def test_repeated_save_is_idempotent_but_changed_payload_is_rejected(self):
        first, _ = self.store.create(record(), "repeat-key")
        second, created = self.store.create(record(), "repeat-key")
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(created)
        with self.assertRaises(Problem) as caught:
            self.store.create(record(title="Different role"), "repeat-key")
        self.assertEqual(caught.exception.code, "key_conflict")

    def test_concurrent_duplicate_saves_produce_one_record(self):
        def create(index):
            try:
                self.store.create(record(), f"parallel-{index}")
                return "created"
            except Problem as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(create, range(4)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("possible_duplicate"), 3)
        self.assertEqual(len(self.store.applications()), 1)

    def test_normalized_duplicate_and_unknown_cycle_are_conservative(self):
        self.store.create(record(cycle="2027–28"), "normalize-1")
        for cycle in ("2027-28", ""):
            with self.assertRaises(Problem) as caught:
                self.store.create(record(organization="  EXAMPLE   EMPLOYER ", cycle=cycle), "normalize-"+cycle)
            self.assertEqual(caught.exception.code, "possible_duplicate")

    def test_scholarship_cycles_stay_separate_and_type_filters_work(self):
        scholar = record(type="scholarship", stage="Submitted", cycle="2026–27")
        self.store.create(scholar, "scholar-1")
        self.store.create({**scholar, "cycle": "2027–28"}, "scholar-2")
        self.store.create(record(), "internship-1")
        self.assertEqual(len(self.store.applications("scholarship")), 2)
        self.assertEqual(len(self.store.applications("internship")), 1)

    def test_wrong_stage_invalid_date_and_unsafe_url_are_rejected(self):
        for changes in ({"type": "scholarship"}, {"submitted_date": "2026-02-30"},
                        {"url": "javascript:alert(1)"}, {"url": "https://user:secret@example.com"}):
            with self.subTest(changes=changes), self.assertRaises(Problem):
                self.store.create(record(**changes), "invalid-save")
        self.assertEqual(self.store.applications(), [])

    def test_update_preserves_history_and_rejects_stale_revision(self):
        first, _ = self.store.create(record(submitted_date="2026-10-01"), "history-1")
        update = {"revision": 1, "stage": "Interview", "submitted_date": "2026-10-02", "reason": "Email and corrected date"}
        self.store.update(first["id"], update)
        with self.assertRaises(Problem) as caught:
            self.store.update(first["id"], update)
        self.assertEqual(caught.exception.code, "stale_revision")
        reopened = self.store.application(first["id"])
        self.assertEqual(reopened["events"][1]["payload"]["before"]["stage"], "Applied")
        self.assertEqual(reopened["events"][1]["payload"]["after"]["stage"], "Interview")

    def test_notes_and_task_resolution_are_persistent_and_audited(self):
        first, _ = self.store.create(record(), "notes-save")
        self.store.note(first["id"], {"note": "Prepare project examples"})
        task = self.store.create_task({"application_id": first["id"], "title": "Prepare", "priority": "review", "due_date": "2027-01-10"})
        self.store.resolve_task(task["id"])
        self.store.resolve_task(task["id"])
        reopened = Store(self.path).application(first["id"])
        self.assertEqual(reopened["tasks"][0]["status"], "resolved")
        self.assertEqual([event["kind"] for event in reopened["events"]], ["created", "note", "task_created", "task_resolved"])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.server = make_server(Path(self.directory.name) / "http.sqlite3")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        with urllib.request.urlopen(self.base) as response:
            document = response.read().decode()
            self.token = re.search(r'name="lelouvre-token" content="([a-f0-9]+)"', document)[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, data=None, **headers):
        supplied = {"Content-Type": "application/json", "X-Lelouvre-Token": self.token,
                    "Idempotency-Key": "http-save-key", **headers}
        request = urllib.request.Request(self.base+path, data=json.dumps(data).encode() if data is not None else None, headers=supplied)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def test_save_reload_and_csv(self):
        status, body, _ = self.request("/api/applications", record(organization="=DANGEROUS()"))
        self.assertEqual(status, 201)
        application_id = json.loads(body)["id"]
        status, body, _ = self.request("/api/applications/"+application_id)
        self.assertEqual(json.loads(body)["origin"], "manual")
        status, body, headers = self.request("/api/export.csv")
        rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
        self.assertEqual(rows[1][2], "'=DANGEROUS()")
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_cross_origin_missing_token_and_wrong_host_cannot_mutate(self):
        for headers in ({"Origin": "https://untrusted.example"}, {"X-Lelouvre-Token": ""}, {"Host": "untrusted.example"}):
            with self.subTest(headers=headers):
                status, _, _ = self.request("/api/applications", record(), **headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.server.store.applications(), [])

    def test_no_sample_data_or_fake_capabilities(self):
        _, body, _ = self.request("/api/state")
        capabilities = json.loads(body)["capabilities"]
        self.assertTrue(capabilities["manual_tracker"])
        self.assertTrue(capabilities["evidence_bank"])
        self.assertIn("demo_mode", capabilities)
        self.assertFalse(capabilities["email"])
        _, body, _ = self.request("/api/applications")
        self.assertEqual(json.loads(body), [])

    def test_unrecognized_routes_and_input_fail_cleanly(self):
        for path in ("/../../lelouvre/store.py", "/api/applications/missing"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/api/applications", {"type": "scholarship"})[0], 400)


if __name__ == "__main__":
    unittest.main()
