import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lelouvre.claim_check import check_bullet, filter_bullets
from lelouvre.demo import DEMO_ENTRIES, is_demo
from lelouvre.evidence_bank import EvidenceBank
from lelouvre.form_reader import run_fixture_form
from lelouvre.scout import ScoutStore
from lelouvre.store import Store
from lelouvre.tailor import tailor_bullets_offline, validate_tailor_payload

TEST_ROOT = Path(__file__).resolve().parent.parent / ".tmp"


class DemoPackTests(unittest.TestCase):
    def test_demo_entries_have_stable_ids(self):
        self.assertGreaterEqual(len(DEMO_ENTRIES), 5)
        ids = [e["id"] for e in DEMO_ENTRIES]
        self.assertEqual(len(ids), len(set(ids)))

    @mock.patch.dict(os.environ, {"LELOUVRE_DEMO": "1"})
    def test_demo_bank_seeds_fake_profile_data(self):
        directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        store = Store(Path(directory.name) / "demo.sqlite3")
        ScoutStore(store)
        bank = EvidenceBank(store)
        snap = bank.snapshot()
        self.assertTrue(any(e["id"].startswith("demo-ev-") for e in snap["entries"]))
        self.assertTrue(any("Demo" in s["answer"] for s in snap["screening_answers"]))
        directory.cleanup()

    def test_claim_check_rejects_inflated_bullet(self):
        entry = DEMO_ENTRIES[0]
        entries = {entry["id"]: entry}
        bad = {"text": "Scaled Kubernetes to 10M users with Rust.", "source_id": entry["id"]}
        self.assertIsNotNone(check_bullet(bad, entries))
        good = {"text": entry["results"][0], "source_id": entry["id"]}
        self.assertIsNone(check_bullet(good, entries))

    def test_offline_tailor_returns_linked_bullets(self):
        bullets = tailor_bullets_offline(
            {"description": "Python FastAPI PostgreSQL"},
            DEMO_ENTRIES,
        )
        self.assertGreaterEqual(len(bullets), 4)
        validate_tailor_payload({"bullets": bullets[:6]})
        accepted, rejected = filter_bullets(bullets, {e["id"]: e for e in DEMO_ENTRIES})
        self.assertGreaterEqual(len(accepted), 4)

    def test_form_fixture_stops_at_sponsorship(self):
        result = run_fixture_form()
        self.assertEqual(result["outcome"], "needs_you")
        self.assertEqual(result["handoff"]["reason_code"], "authorization_question")
        self.assertIn("first_name", result["filled"])
        self.assertNotIn("sponsorship", result["filled"])


if __name__ == "__main__":
    unittest.main()
