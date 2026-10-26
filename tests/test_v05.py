from lelouvre.demo import DEMO_ENTRIES
import json
import tempfile
import unittest
from pathlib import Path

from lelouvre.evidence_bank import EvidenceBank
from lelouvre.scout import ScoutStore
from lelouvre.handoff import build_handoff, OUTCOME_NEEDS_YOU
from lelouvre.store import Store
from lelouvre.tailoring import one_line_fit, tailor_documents, verify_documents
from lelouvre.today import build_today

TEST_ROOT = Path(__file__).resolve().parent.parent / ".tmp"
TEST_ROOT.mkdir(exist_ok=True)


class V05Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.store = Store(Path(self.directory.name) / "v05.sqlite3")
        ScoutStore(self.store)
        self.bank = EvidenceBank(self.store)
        for entry in DEMO_ENTRIES:
            self.bank.upsert_entry(entry)

    def tearDown(self):
        self.directory.cleanup()

    def test_explicit_fictional_evidence_persists(self):
        snap = self.bank.snapshot()
        self.assertGreaterEqual(len(snap["entries"]), 3)
        self.assertTrue(snap["master_resume"].get("bullets"))

    def test_tailored_bullets_link_to_evidence(self):
        snap = self.bank.snapshot()
        evaluation = {"matched_skills": [{"skill": "Python"}], "reasons": [], "gaps": []}
        tailored = tailor_documents(
            snap,
            organization="Datadog",
            title="Software Engineering Intern",
            location="New York, NY",
            description="Python Java React backend cloud internship summer 2027",
            evaluation=evaluation,
        )
        self.assertTrue(tailored["resume"]["bullets"])
        for bullet in tailored["resume"]["bullets"]:
            self.assertIn(bullet["evidence_id"], {e["id"] for e in snap["entries"]})
        failures = verify_documents(snap, tailored)
        self.assertEqual(failures, [])

    def test_handoff_message_plain_language(self):
        handoff = build_handoff("Cloudflare", "Software Engineer Intern", "authorization_question")
        self.assertEqual(handoff["outcome"], OUTCOME_NEEDS_YOU)
        self.assertIn("Cloudflare", handoff["message"])
        self.assertIn("sponsorship", handoff["why"].casefold())

    def test_today_three_blocks(self):
        evaluation = json.dumps(
            {
                "target": "potential_match",
                "priority": 80,
                "season": "confirmed",
                "track": "SWE",
                "reasons": [{"reason": "Backend role", "excerpt": "Python"}],
                "matched_skills": [{"skill": "Python", "posting_excerpt": "python"}],
                "gaps": [],
                "blockers": [],
            }
        )
        with self.store.connect() as connection:
            connection.execute(
                """INSERT INTO opportunities
                (id,source_id,external_id,type,organization,title,location,url,kind,availability,
                 first_seen,last_seen,last_checked,content_hash,description,evaluation,disposition,last_change)
                VALUES ('o1','cloudflare','1','internship','Datadog','Intern','NY','https://example.com',
                 'listing','listed','t','t','t','h','desc',?,'new','discovered')""",
                (evaluation,),
            )
        view = build_today(self.store, [])
        self.assertEqual(len(view["new_roles"]), 1)
        self.assertIn("Datadog", view["new_roles"][0]["fit_reason"])
        self.assertIn("needs_you", view)


if __name__ == "__main__":
    unittest.main()
