import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lelouvre.internship_agent import InternshipAgent
from lelouvre.scout import ScoutStore
from lelouvre.store import Store

TEST_ROOT = Path(__file__).resolve().parent.parent / ".tmp"


class InternshipAgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.store = Store(Path(self.directory.name) / "ia.sqlite3")
        ScoutStore(self.store)
        evaluation = json.dumps(
            {
                "target": "potential_match",
                "priority": 90,
                "season": "confirmed",
                "verification": "verified_ats",
                "track": "SWE",
                "reasons": [],
                "matched_skills": [],
                "gaps": [],
                "blockers": [],
                "eligibility": "Needs review",
                "rules_version": "rules-4-role-season-location",
            }
        )
        with self.store.connect() as connection:
            connection.execute(
                """INSERT INTO opportunities
                (id,source_id,external_id,type,organization,title,location,url,kind,availability,
                 first_seen,last_seen,last_checked,content_hash,description,evaluation,disposition,last_change)
                VALUES ('save-me','cloudflare','1','internship','Acme','SWE Intern Summer 2027','NY',
                 'https://boards.greenhouse.io/acme/jobs/1','listing','listed',
                 't','t','t','h','Python',?,'new','discovered')""",
                (evaluation,),
            )
        self.scout = MagicMock()
        self.scout.lock = __import__("threading").Lock()
        self.scout.start = MagicMock(return_value={"id": "scout-1", "status": "running"})
        self.apply = MagicMock()
        self.apply.status.return_value = {"browser_available": False}
        self.apply.settings = MagicMock()
        self.apply.start = MagicMock(return_value={"id": "pipe-1", "status": "running"})
        self.apply.lock = __import__("threading").Lock()
        self.agent = InternshipAgent(self.store, self.scout, self.apply)

    def tearDown(self):
        self.directory.cleanup()

    def test_status_reports_submit_hosts(self):
        self.apply.status.return_value = {"browser_available": False, "execution_hosts": ["127.0.0.1", "boards.greenhouse.io"]}
        status = self.agent.status()
        self.assertTrue(status["can_submit_employers"])

    def test_auto_save_moves_potential_matches_to_saved(self):
        count = self.agent._auto_save_matches()
        self.assertEqual(count, 1)
        with self.store.connect() as connection:
            disposition = connection.execute(
                "SELECT disposition FROM opportunities WHERE id='save-me'"
            ).fetchone()[0]
        self.assertEqual(disposition, "saved")


if __name__ == "__main__":
    unittest.main()
