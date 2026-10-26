import json
import tempfile
import unittest
from pathlib import Path

from lelouvre.scout import ScoutStore
from lelouvre.scout_fit import enrich_new_discovery_fits, fit_display, gemma_fit_for_opportunity
from lelouvre.store import Store
from lelouvre.traces import TraceLog


class ScoutFitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "fit.sqlite3")
        ScoutStore(self.store)
        evaluation = {
            "target": "potential_match",
            "track": "software",
            "matched_skills": [{"skill": "Python", "posting_excerpt": "python"}],
            "reasons": [],
            "blockers": [],
        }
        with self.store.connect() as connection:
            connection.execute(
                """INSERT INTO opportunities
                (id,source_id,external_id,type,organization,title,location,url,kind,availability,
                 first_seen,last_seen,last_checked,content_hash,description,evaluation,disposition,last_change)
                VALUES ('opp-1','cloudflare','ext-1','internship','Acme','Intern','Remote','https://example.com',
                 'listing','listed','t','t','t','hash','Build APIs in Python.',?,'new','discovered')""",
                (json.dumps(evaluation),),
            )

    def tearDown(self):
        self.directory.cleanup()

    def test_offline_enrich_uses_rules(self):
        import os

        os.environ["LELOUVRE_TAILOR_OFFLINE"] = "1"
        try:
            result = enrich_new_discovery_fits(self.store, limit=2)
            self.assertEqual(result["enriched"], 1)
            with self.store.connect() as connection:
                row = connection.execute("SELECT evaluation FROM opportunities WHERE id='opp-1'").fetchone()
            ev = json.loads(row["evaluation"])
            self.assertEqual(ev["gemma_fit"]["source"], "rules")
            blurb, source = fit_display(ev, "Acme", "Intern")
            self.assertEqual(source, "rules")
            self.assertIn("Python", blurb)
        finally:
            os.environ.pop("LELOUVRE_TAILOR_OFFLINE", None)

    def test_gemma_fit_logs_trace(self):
        import os

        os.environ.pop("LELOUVRE_TAILOR_OFFLINE", None)

        def transport(url, payload, timeout=120):
            return {
                "message": {"content": "Python APIs match your project work."},
                "eval_duration": 5_000_000,
                "eval_count": 12,
                "prompt_eval_count": 40,
            }

        from lelouvre.gemma import GemmaClient

        client = GemmaClient(transport=transport)
        client._get = lambda url, timeout=10: {"models": [{"name": client.model}]}

        with self.store.connect() as connection:
            row = dict(connection.execute("SELECT * FROM opportunities WHERE id='opp-1'").fetchone())
        traces = TraceLog(self.store)
        updated = gemma_fit_for_opportunity(row, client=client, trace_log=traces)
        self.assertEqual(updated["gemma_fit"]["source"], "gemma")
        kinds = [t["kind"] for t in traces.list(kind="gemma_scout_fit")]
        self.assertEqual(len(kinds), 1)


if __name__ == "__main__":
    unittest.main()
