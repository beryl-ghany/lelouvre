"""Hosted previews cannot expose real defaults or mutate state."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from lelouvre.evidence_bank import EvidenceBank
from lelouvre.profile_store import ProfileStore
from lelouvre.server import make_server
from lelouvre.store import Store

ROOT = Path(__file__).resolve().parent.parent / '.tmp'
ROOT.mkdir(exist_ok=True)


class PrivacyDefaultsTests(unittest.TestCase):
    def test_fresh_real_workspace_contains_no_candidate_facts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch.dict(os.environ, {'LELOUVRE_DEMO': '0'}):
            store = Store(Path(directory) / 'real.sqlite3')
            self.assertTrue(all(value == '' for value in ProfileStore(store).get().values()))
            snapshot = EvidenceBank(store).snapshot()
            self.assertEqual(snapshot['entries'], [])
            self.assertEqual(snapshot['screening_answers'], [])
            self.assertEqual(snapshot['master_resume']['name'], '')

    def test_demo_resume_header_matches_fictional_profile(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch.dict(os.environ, {'LELOUVRE_DEMO': '1'}):
            store = Store(Path(directory) / 'demo.sqlite3')
            profile = ProfileStore(store).get()
            bank = EvidenceBank(store)
            self.assertEqual(bank.snapshot()['master_resume']['name'], profile['name'])
            bank.upsert_entry({'title': 'Extra demo project'})
            self.assertEqual(bank.snapshot()['master_resume']['name'], 'Jordan Demo')

    def test_hosted_mode_refuses_real_workspace_before_opening_database(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch.dict(os.environ, {'LELOUVRE_DEMO': '0'}):
            path = Path(directory) / 'must-not-exist.sqlite3'
            with self.assertRaises(ValueError):
                make_server(path, hosted=True, access_token='test-only-token')
            self.assertFalse(path.exists())


class HostedReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'LELOUVRE_DEMO': '1', 'LELOUVRE_TAILOR_OFFLINE': '1'})
        self.env.start()
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.token = 'test-only-token'
        self.server = make_server(Path(self.directory.name) / 'demo.sqlite3', hosted=True, access_token=self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.agent.close()
        self.thread.join()
        self.directory.cleanup()
        self.env.stop()

    def request(self, path, data=None, token=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Lelouvre-Token'] = self.token
        req = urllib.request.Request(self.base + path, headers=headers, data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_fictional_preview_api_is_public(self):
        self.assertEqual(self.request('/health', token=False)[0], 200)
        self.assertEqual(self.request('/api/state', token=False)[0], 200)
        status, body = self.request('/api/state')
        self.assertEqual(status, 200)
        config = json.loads(body)
        self.assertTrue(config['capabilities']['read_only'])
        self.assertEqual(config['profile']['name'], 'Jordan Demo')
        self.assertFalse(config['capabilities']['gemma']['available'])

    def test_all_mutations_are_denied_even_with_token(self):
        for path in ['/health', '/api/profile', '/api/agent/run', '/api/internship-agent/run', '/api/gemma/chat', '/api/demo/form-run', '/api/application-runs/prepare', '/api/application-runs/example/approve', '/api/application-runs/example/execute', '/api/evidence/entries', '/api/applications', '/api/apply-agent/settings']:
            with self.subTest(path=path):
                status, body = self.request(path, {})
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body)['code'], 'read_only_demo')
        self.assertEqual(self.server.store.applications(), [])

    def test_today_does_not_invoke_models_or_write_traces(self):
        with patch('lelouvre.server.enrich_new_discovery_fits', side_effect=AssertionError('No model work in hosted preview')), patch('lelouvre.server.build_overnight_digest', side_effect=AssertionError('No inference in hosted preview')):
            status, body = self.request('/api/today')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['overnight_digest']['source'], 'rules')
        self.assertEqual(json.loads(self.request('/api/traces')[1]), [])
