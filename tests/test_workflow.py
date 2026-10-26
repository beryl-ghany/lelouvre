"""Regression checks for approval, reviewed answers, and durable submission claims."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lelouvre.application_agent import ApplicationAgent
from lelouvre.forms import FormParser, CONFIRMATION
from lelouvre.scout import evaluate
from lelouvre.store import Store, Problem
from tests.test_tracker import HTTPTests

ROOT = Path(__file__).resolve().parent.parent / '.tmp'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.store = Store(Path(self.directory.name) / 'regression.sqlite3')
        self.agent = ApplicationAgent(self.store)
        self.offline = patch.dict(os.environ, {'LELOUVRE_TAILOR_OFFLINE': '1'})
        self.offline.start()

    def tearDown(self):
        self.offline.stop()
        self.directory.cleanup()

    def prepare(self, fields=None):
        return self.agent.prepare({'destination': 'https://job-boards.greenhouse.io/example/jobs/123',
            'fields': fields or [{'name': 'first_name', 'required': True}],
            'application': {'organization': 'Example', 'title': 'Software Intern', 'cycle': 'Summer 2027'}})

    def test_approval_does_not_override_claim_failures(self):
        run = self.prepare()
        run['packet']['tailored']['verification_failures'] = [{'message': 'Unsupported metric'}]
        self.agent._save_packet(run['id'], run['packet'], run['status'])
        with self.assertRaises(Problem) as caught:
            self.agent.approve_packet(run['id'])
        self.assertEqual(caught.exception.code, 'verification_failed')

    def test_profile_persists_and_invalidates_approval(self):
        run = self.agent.approve_packet(self.prepare()['id'])
        self.agent.profiles.save({'email': 'candidate@example.com', 'first_name': 'Jordan'})
        self.assertEqual(ApplicationAgent(self.store).profiles.get()['email'], 'candidate@example.com')
        self.assertFalse(self.agent.run(run['id'])['packet']['approved'])
        with self.assertRaises(Problem):
            self.agent.approve_packet(run['id'])

    def test_review_exact_authorization_and_dropdown_answers(self):
        run = self.prepare([{'name': 'question_123', 'label': 'Are you legally authorised to work?', 'required': True,
                            'options': [{'label': 'Yes', 'value': '1'}, {'label': 'No', 'value': '0'}]}])
        self.assertEqual(run['policy']['decision'], 'review')
        with self.assertRaises(Problem):
            self.agent.review_answers(run['id'], {'answers': {'question_123': 'Yes'}})
        run = self.agent.review_answers(run['id'], {'answers': {'question_123': '1'}})
        self.assertEqual(run['policy']['decision'], 'approved')
        self.assertFalse(run['packet']['approved'])
        self.assertTrue(self.agent.approve_packet(run['id'])['packet']['approved'])

    def test_name_is_split_and_missing_email_is_not_invented(self):
        run = self.prepare([{'name': 'first_name', 'required': True}, {'name': 'last_name', 'required': True}, {'name': 'email', 'required': True}])
        self.assertEqual(run['packet']['answers']['first_name'], 'Jordan')
        self.assertEqual(run['packet']['answers']['last_name'], 'Demo')
        self.assertNotIn('email', run['packet']['answers'])
        self.assertEqual(run['policy']['decision'], 'review')

    def test_claim_prevents_duplicate_runs_and_uncertain_retry(self):
        run = self.agent.approve_packet(self.prepare()['id'])
        other = self.agent.approve_packet(self.prepare()['id'])
        self.assertTrue(self.agent._claim_submission(run))
        self.assertFalse(self.agent._claim_submission(run))
        with self.assertRaises(Problem):
            self.agent._claim_submission(other)
        self.agent._status(run['id'], 'receipt_unconfirmed', receipt={'confirmed': False, 'submitted': True})
        self.assertEqual(self.agent.execute(run['id'], auto_submit=True)['status'], 'receipt_unconfirmed')

    def test_stale_request_cannot_submit_changed_answers(self):
        run = self.agent.approve_packet(self.prepare()['id'])
        self.agent.review_answers(run['id'], {'answers': {'first_name': 'Updated'}})
        with self.assertRaises(Problem):
            self.agent._claim_submission(run)

    def test_labels_options_and_hidden_values_are_preserved(self):
        parser = FormParser()
        parser.feed('<form action="/apply"><label for="q">Require sponsorship?</label><select id="q" name="q" required><option value="1">Yes</option></select><input type="hidden" name="csrf" value="abc"></form>')
        parser.close()
        self.assertEqual(parser.fields[0]['label'], 'Require sponsorship?')
        self.assertEqual(parser.fields[0]['options'], [{'value': '1', 'label': 'Yes'}])
        self.assertEqual(parser.fields[1]['value'], 'abc')

    def test_confirmation_rejects_generic_thanks(self):
        self.assertFalse(CONFIRMATION.search('Thank you for visiting. Email confirmation preferences.'))
        self.assertTrue(CONFIRMATION.search('Your application has been received.'))

    def test_summer_program_dates_but_not_graduation_confirm_season(self):
        self.assertEqual(evaluate('Software Intern (Summer)', 'Boston, MA', 'Program: May 24 - Aug 20, 2027')['season'], 'confirmed')
        self.assertEqual(evaluate('Software Intern (Summer)', 'Boston, MA', 'Expected graduation May 2027')['season'], 'unknown')


class WorkflowHTTPTests(HTTPTests):
    def test_approval_route_and_settings_accept_actual_ui_values(self):
        with patch.dict(os.environ, {'LELOUVRE_TAILOR_OFFLINE': '1'}):
            status, body, _ = self.request('/api/application-runs/prepare', {'destination': 'https://example.com/apply', 'fields': [{'name': 'name'}], 'application': {'organization': 'Example', 'title': 'Software Intern', 'cycle': 'Summer 2027'}})
            self.assertEqual(status, 201)
            run_id = json.loads(body)['id']
            self.assertEqual(self.request('/api/application-runs/' + run_id + '/approve', {})[0], 200)
        status, body, _ = self.request('/api/apply-agent/settings', {'apply_mode': 'auto_when_safe'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['apply_mode'], 'auto_when_safe')
        self.assertEqual(self.request('/api/apply-agent/settings', {'apply_mode': True})[0], 400)

    def test_profile_route_and_explicit_submission_argument(self):
        self.assertEqual(self.request('/api/profile', {'email': 'test@example.com'})[0], 200)
        self.assertEqual(json.loads(self.request('/api/profile')[1])['email'], 'test@example.com')
        with patch.object(self.server.application_agent, 'execute', return_value={'status': 'prepared'}) as execute:
            self.request('/api/application-runs/test/execute', {})
            self.assertFalse(execute.call_args.kwargs['auto_submit'])
            self.request('/api/application-runs/test/execute', {'auto_submit': True})
            self.assertTrue(execute.call_args.kwargs['auto_submit'])
