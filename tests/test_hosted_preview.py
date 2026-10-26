import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from lelouvre.server import make_server
from lelouvre.store import Store


class HostedPreviewTests(unittest.TestCase):
    @patch.dict(os.environ, {"LELOUVRE_DEMO": "1", "LELOUVRE_TAILOR_OFFLINE": "1"})
    def test_preview_is_public_fictional_and_cannot_write(self):
        with tempfile.TemporaryDirectory() as directory:
            private_path = Path(directory) / "private.sqlite3"
            private_store = Store(private_path)
            private_store.create({"type": "internship", "organization": "Private employer",
                                  "title": "Private role", "cycle": "2027", "stage": "Saved"}, "private")
            server = make_server(private_path, hosted=True, access_token="test-secret")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base + "/api/profile") as response:
                    self.assertEqual(json.load(response)["name"], "Jordan Demo")
                with urllib.request.urlopen(base + "/api/applications") as response:
                    self.assertEqual(json.load(response), [])
                request = urllib.request.Request(base + "/api/profile", data=b'{"name":"Changed"}',
                                                 headers={"Content-Type": "application/json", "X-Lelouvre-Token": "test-secret"})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 403)
                self.assertEqual(json.load(caught.exception)["code"], "read_only_demo")
                self.assertEqual(len(private_store.applications()), 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                server.demo_directory.cleanup()

    @patch.dict(os.environ, {"LELOUVRE_DEMO": "0"})
    def test_private_hosted_workspace_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.sqlite3"
            with self.assertRaises(ValueError):
                make_server(path, hosted=True, access_token="test-secret")
            self.assertFalse(path.exists())
