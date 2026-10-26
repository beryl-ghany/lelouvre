"""Browser application executor: inspect, fill approved answers, verify, submit once."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .forms import BROWSER_FIELDS, CONFIRMATION
from .store import Problem, now
from .verify import classify_apply_url

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(__file__).resolve().parent.parent / ".venv" / "browsers"))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class BrowserExecutor:
    def __init__(self, profile, *, headless=True, submit=False):
        self.profile = profile
        self.headless = headless
        self.submit = submit

    def available(self):
        if sync_playwright is None:
            return False
        try:
            with sync_playwright() as p:
                return Path(p.chromium.executable_path).is_file()
        except Exception:
            return False

    @staticmethod
    def _destination(destination):
        verified = classify_apply_url(destination)
        if not verified or verified['platform'] not in ('greenhouse', 'lever'):
            raise Problem('This browser application platform is not supported.', 409, 'platform_unsupported')
        return verified

    def inspect(self, destination):
        verified = self._destination(destination)
        if not self.available():
            raise Problem('Browser support needs Playwright and its Chromium browser installed.', 503, 'playwright_unavailable')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                page = browser.new_page()
                page.goto(destination, wait_until='domcontentloaded', timeout=45000)
                page.locator('form input').first.wait_for(timeout=15000)
                fields = self._read_fields(page, verified)
                if not fields:
                    raise Problem('No application form was found.', 409, 'unfamiliar_form')
                return {'fields': fields}
            finally:
                browser.close()

    def run(self, destination, approved_answers, *, before_submit=None, expected_fields=None):
        verified = self._destination(destination)
        if not self.available():
            raise Problem('Install browser support before submitting.', 503, 'playwright_unavailable')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                page = browser.new_page()
                page.goto(destination, wait_until='domcontentloaded', timeout=45000)
                page.locator('form input').first.wait_for(timeout=15000)
                fields = self._read_fields(page, verified)
                result = {'platform': verified['platform'], 'filled_fields': [], 'submitted': False,
                          'confirmed': False, 'final_url': page.url, 'captured_at': now()}
                if not fields:
                    return {**result, 'evidence': 'No application form was found.'}
                expected = {f['name']: f for f in expected_fields or []}
                for field in fields:
                    if field['type'] in ('hidden', 'submit', 'button'):
                        continue
                    old = expected.get(field['name'])
                    # A changed label/options/requiredness invalidates prior review.
                    if expected_fields is not None and (not old or any(old.get(k) != field.get(k) for k in ('label', 'required', 'type')) or old.get('options', []) != field.get('options', [])):
                        return {**result, 'evidence': 'The form changed since preparation. Prepare and review again.'}
                result['filled_fields'] = self._fill_fields(page, fields, approved_answers)
                after_fields = self._read_fields(page, verified)
                schema = lambda fs: [(f['name'], f['type'], f.get('required'), f.get('label')) for f in fs if f['type'] not in ('hidden', 'submit', 'button')]
                if schema(after_fields) != schema(fields):
                    return {**result, 'evidence': 'Answering this form revealed additional or changed questions. Prepare and review again.'}
                missing = [f.get('label', f['name']) for f in fields if f.get('required') and f['type'] not in ('hidden', 'submit', 'button') and not approved_answers.get(f['name'])]
                invalid = page.locator('form :invalid:not([type=checkbox]):not([type=radio])').count()
                # Some React forms mark every checkbox required even when one choice suffices.
                for field in fields:
                    if field.get('required') and field['type'] in ('checkbox', 'radio'):
                        controls = page.locator('[name=' + json.dumps(field['name']) + ']')
                        if not any(controls.nth(i).is_checked() for i in range(controls.count())):
                            missing.append(field['label'])
                if missing or invalid:
                    return {**result, 'evidence': 'Required fields still need attention: ' + ', '.join(missing[:5]) if missing else 'The employer form reports incomplete or invalid answers.'}
                # Visible challenges need the user; no automated challenge solving.
                if page.locator('iframe[src*="captcha"]:visible, .g-recaptcha:visible, .h-captcha:visible').count():
                    return {**result, 'evidence': 'Complete the employer CAPTCHA manually.'}
                before = page.locator('body').inner_text()
                if CONFIRMATION.search(before):
                    return {**result, 'evidence': 'The page already contains confirmation text. Check existing applications.'}
                if not self.submit:
                    return {**result, 'evidence': 'Approved fields checked. Submission was not requested.'}
                button = page.get_by_role('button', name=re.compile(r'^(Submit application|Submit|Apply now|Send application)$', re.I))
                if button.count() != 1:
                    return {**result, 'evidence': 'A unique final submission button was not found.'}
                if before_submit is None or not before_submit():
                    return {**result, 'evidence': 'Submission already started or has not been authorized.'}
                result['submitted'] = True
                button.click(timeout=10000)
                try:
                    page.wait_for_function(r"() => /application\s+(?:(?:has been|was|is)\s+)?(?:successfully\s+)?(?:received|submitted)|thank you for (?:applying|your application)/i.test(document.body.innerText)", timeout=20000)
                except Exception:
                    pass
                text = page.locator('body').inner_text()
                result.update(confirmed=bool(CONFIRMATION.search(text)), final_url=page.url,
                              evidence='Employer confirmed receipt.' if CONFIRMATION.search(text) else 'No confirmation received. Check employer before retrying.')
                return result
            finally:
                browser.close()

    def _read_fields(self, page, verified):
        fields = page.evaluate(BROWSER_FIELDS)
        api_questions = {}
        if verified['platform'] == 'greenhouse':
            from urllib.parse import quote
            url = f"https://boards-api.greenhouse.io/v1/boards/{quote(verified['board'], safe='')}/jobs/{verified['external_job_id']}?questions=true"
            try:
                response = page.request.get(url, timeout=15000)
                if response.ok:
                    for q in response.json().get('questions', []):
                        for f in q.get('fields', []):
                            api_questions[f['name']] = (q, f)
            except Exception:
                pass
        for field in fields:
            if field['name'] == 'resume':
                field['required'] = True
            if field['name'] in api_questions:
                q, f = api_questions[field['name']]
                field['required'] = field['required'] or q.get('required', False)
                field['label'] = q['label'].strip()
                if f.get('values'):
                    field['options'] = [{'label': str(o['label']), 'value': str(o['value'])} for o in f['values']]
            if field['type'] == 'combobox' and not field['options']:
                control = page.locator('[id=' + json.dumps(field['id']) + ']')
                try:
                    control.click(timeout=3000)
                    labels = page.get_by_role('option').all_text_contents()
                    field['options'] = [{'label': label.strip(), 'value': label.strip()} for label in labels if label.strip()]
                    control.press('Escape')
                except Exception:
                    # Dynamic location lookups can still be entered explicitly and must match one option.
                    pass
        return fields

    def _fill_fields(self, page, fields, answers):
        filled = []
        for field in fields:
            name = field['name']
            if name not in answers or field['type'] in ('hidden', 'submit', 'button'):
                continue
            locator = page.locator('[name=' + json.dumps(name) + ']')
            if locator.count() == 0 and field.get('id'):
                locator = page.locator('[id=' + json.dumps(field['id']) + ']')
            value = answers[name]
            try:
                if value == '' or value == []:
                    continue
                if field['type'] == 'combobox':
                    selected = value if isinstance(value, list) else [value]
                    for v in selected:
                        option = next((o['label'] for o in field.get('options', []) if str(o['value']) == str(v)), str(v))
                        locator.click()
                        locator.fill(option)
                        choice = page.get_by_role('option', name=option, exact=True)
                        choice.wait_for(timeout=5000)
                        if choice.count() != 1:
                            raise ValueError('Ambiguous option')
                        choice.click()
                elif field['type'] == 'file':
                    locator.set_input_files(str(value))
                elif field['type'] in ('select-one', 'select-multiple', 'select'):
                    locator.select_option(value if isinstance(value, list) else str(value))
                elif field['type'] in ('checkbox', 'radio'):
                    values = value if isinstance(value, list) else [value]
                    for i in range(locator.count()):
                        control = locator.nth(i)
                        selected = str(control.get_attribute('value') or 'on') in values
                        if field['type'] == 'radio':
                            if selected:
                                control.check()
                        else:
                            control.set_checked(selected)
                elif locator.count() == 1:
                    locator.fill(str(value))
                else:
                    continue
                filled.append(name)
            except Exception:
                raise Problem(f"Could not fill {field.get('label') or name}. Open this application to finish it.", 409, 'low_confidence_field')
        return filled
