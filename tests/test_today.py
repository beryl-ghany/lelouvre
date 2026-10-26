import json
import tempfile
import unittest
from pathlib import Path

from lelouvre.scout import ScoutStore
from lelouvre.store import Store
from lelouvre.today import build_today

TEST_ROOT = Path(__file__).resolve().parent.parent / ".tmp"
TEST_ROOT.mkdir(exist_ok=True)


class TodayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.store = Store(Path(self.directory.name) / "today.sqlite3")
        ScoutStore(self.store)
        evaluation = json.dumps(
            {
                "target": "potential_match",
                "priority": 80,
                "season": "confirmed",
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
                VALUES ('o1','cloudflare','1','internship','Acme','Intern Summer 2027','NY','https://example.com',
                 'listing','listed','t','t','t','h','desc',?,'new','discovered')""",
                (evaluation,),
            )
            connection.execute(
                """INSERT INTO opportunities
                (id,source_id,external_id,type,organization,title,location,url,kind,availability,
                 first_seen,last_seen,last_checked,content_hash,description,evaluation,disposition,last_change)
                VALUES ('o2','cloudflare','2','internship','Beta','Intern Summer 2027','NY','https://example.com',
                 'listing','listed','t','t','t','h','desc',?,'saved','discovered')""",
                (evaluation,),
            )

    def tearDown(self):
        self.directory.cleanup()

    def test_today_includes_new_roles(self):
        view = build_today(self.store, [])
        self.assertEqual(len(view["new_roles"]), 1)
        self.assertEqual(view["new_roles"][0]["id"], "o1")
        self.assertEqual(view["primary_action"]["label"], "Find new roles")


if __name__ == "__main__":
    unittest.main()
