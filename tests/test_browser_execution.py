"""Local browser tests. No employer requests or submissions."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from lelouvre.browser_executor import BrowserExecutor, sync_playwright

ROOT = Path(__file__).resolve().parent.parent / '.tmp'
FORM = '''<form><label for="first_name">First Name</label><input id="first_name" required>
<label for="last_name">Last Name</label><input id="last_name" required>
<label for="email">Email</label><input id="email" type="email" required>
<label for="resume">Resume</label><input id="resume" type="file" required>
<label for="q">Location</label><select id="q" name="q" required><option value="">Choose</option><option value="ny">New York</option></select>
<label><input name="terms" type="checkbox" value="summer" required>Summer</label>
<label><input name="terms" type="checkbox" value="winter" required>Winter</label>
<button type="button" onclick="document.body.innerText='Your application has been received.'">Submit application</button></form>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(FORM.encode())


@unittest.skipIf(sync_playwright is None, 'Project browser environment is optional')
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.resume = Path(self.directory.name) / 'resume.pdf'
        self.resume.write_bytes(b'%PDF-1.4 local upload test')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.executor = BrowserExecutor({}, submit=True)
        # Local test form substitutes for an employer, with no external traffic.
        self.destination = patch.object(BrowserExecutor, '_destination', return_value={'platform': 'lever'})
        self.destination.start()

    def tearDown(self):
        self.destination.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def answers(self):
        return {'first_name': 'Test', 'last_name': 'Candidate', 'email': 'test@example.com',
                'resume': str(self.resume), 'q': 'ny', 'terms': ['summer']}

    def test_upload_ids_select_and_grouped_checkboxes_submit_and_confirm(self):
        fields = self.executor.inspect(self.url)['fields']
        self.assertEqual(len([f for f in fields if f['name'] == 'terms']), 1)
        self.assertIn('first_name', [f['name'] for f in fields])
        receipt = self.executor.run(self.url, self.answers(), before_submit=lambda: True, expected_fields=fields)
        self.assertTrue(receipt['submitted'], receipt)
        self.assertTrue(receipt['confirmed'], receipt)
        self.assertIn('resume', receipt['filled_fields'])

    def test_missing_required_answer_never_claims_submission(self):
        fields = self.executor.inspect(self.url)['fields']
        answers = self.answers()
        del answers['email']
        claims = []
        receipt = self.executor.run(self.url, answers, before_submit=lambda: claims.append(True), expected_fields=fields)
        self.assertFalse(receipt['submitted'])
        self.assertEqual(claims, [])

    def test_changed_form_never_claims_submission(self):
        fields = self.executor.inspect(self.url)['fields']
        fields[0]['label'] = 'Changed question'
        claims = []
        receipt = self.executor.run(self.url, self.answers(), before_submit=lambda: claims.append(True), expected_fields=fields)
        self.assertFalse(receipt['submitted'])
        self.assertEqual(claims, [])

    def test_custom_dropdown_can_be_inspected_and_filled(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content('''<form><input id="first_name"><label for="choice">Team</label>
                  <input id="choice" role="combobox"><div role="option" onclick="document.getElementById('choice').value='Backend'">Backend</div></form>''')
                fields = self.executor._read_fields(page, {'platform': 'lever'})
                choice = next(f for f in fields if f['name'] == 'choice')
                self.assertEqual(choice['options'], [{'label': 'Backend', 'value': 'Backend'}])
                self.executor._fill_fields(page, fields, {'choice': 'Backend'})
                self.assertEqual(page.locator('#choice').input_value(), 'Backend')
            finally:
                browser.close()
