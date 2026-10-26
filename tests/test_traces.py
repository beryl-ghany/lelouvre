import tempfile
import unittest
from pathlib import Path

from lelouvre.store import Store
from lelouvre.traces import TraceLog


class TraceLogTests(unittest.TestCase):
    def test_kind_filter(self):
        directory = tempfile.TemporaryDirectory()
        try:
            store = Store(Path(directory.name) / "tr.sqlite3")
            log = TraceLog(store)
            log.log("gemma_tailor", {"a": 1})
            log.log("gemma_chat", {"b": 2})
            log.log("gemma_tailor", {"a": 3})
            all_rows = log.list()
            self.assertEqual(len(all_rows), 3)
            tailor = log.list(kind="gemma_tailor")
            self.assertEqual(len(tailor), 2)
            self.assertTrue(all(r["kind"] == "gemma_tailor" for r in tailor))
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
