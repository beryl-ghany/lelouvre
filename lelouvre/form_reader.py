"""Read application forms, fill safe fields, stop at authorization / essays."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import pathname2url

from .demo import demo_profile, is_demo
from .handoff import OUTCOME_NEEDS_YOU, build_handoff, outcome_ready
from .application_agent import APPROVED_PROFILE

AUTH_PATTERN = re.compile(
    r"sponsor|sponsorship|visa|work authorization|authorized to work|"
    r"immigration|h-1b|h1b|opt|cpt|require.*work.*permit",
    re.I,
)
ESSAY_PATTERN = re.compile(r"essay|cover letter|why (?:do you|us)|describe|statement", re.I)
CAPTCHA_PATTERN = re.compile(r"captcha|hcaptcha|recaptcha", re.I)


class FieldParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = []
        self._label = ""

    def handle_starttag(self, tag, attrs):
        if tag == "label":
            self._label = ""
        if tag in ("input", "textarea", "select"):
            values = dict(attrs)
            name = values.get("name") or values.get("id")
            if name:
                self.fields.append(
                    {
                        "name": name,
                        "type": values.get("type", tag),
                        "label": self._label.strip(),
                        "required": "required" in values,
                    }
                )

    def handle_data(self, data):
        if data.strip():
            self._label = (self._label + " " + data).strip()


def classify_field(field):
    label = f"{field.get('label', '')} {field.get('name', '')}"
    if CAPTCHA_PATTERN.search(label):
        return "captcha"
    if AUTH_PATTERN.search(label):
        return "authorization_question"
    if ESSAY_PATTERN.search(label):
        return "essay_required"
    return "routine"


def read_form_fields(html):
    parser = FieldParser()
    parser.feed(html)
    return parser.fields


FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "field_type": {
                        "type": "string",
                        "enum": ["routine", "authorization_question", "essay_required", "captcha", "unknown"],
                    },
                },
                "required": ["name", "field_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}


def label_fields_with_model(fields, *, use_gemma=None, trace_log=None):
    """Gemma labels fields; hard authorization/essay rules always win."""
    if use_gemma is None:
        use_gemma = __import__("os").environ.get("LELOUVRE_FORM_GEMMA", "1").lower() in ("1", "true", "yes")
    model_map = {}
    gemma_meta = None
    if use_gemma:
        try:
            from .gemma import GemmaClient

            client = GemmaClient()
            if client.status().get("model_ready"):
                payload, gemma_meta = client.chat_json(
                    [
                        {"role": "system", "content": "Classify each form field. Be conservative on authorization."},
                        {"role": "user", "content": __import__("json").dumps(fields, ensure_ascii=False)},
                    ],
                    FIELD_SCHEMA,
                    timeout=12,
                    with_meta=True,
                )
                model_map = {item["name"]: item["field_type"] for item in payload.get("fields", [])}
                if trace_log:
                    trace_log.log(
                        "gemma_form_label",
                        {"field_count": len(fields), "labeled": len(model_map), "gemma_meta": gemma_meta},
                    )
        except Exception:
            model_map = {}
    labeled = []
    for field in fields:
        rule_code = classify_field(field)
        code = model_map.get(field.get("name"), rule_code)
        if rule_code in ("authorization_question", "essay_required", "captcha"):
            code = rule_code
        labeled.append(
            {
                **field,
                "reason_code": code,
                "classifier": "gemma+rules" if field.get("name") in model_map else "rules",
            }
        )
    return labeled, gemma_meta


def fill_plan(fields, profile=None):
    profile = profile or (demo_profile() if is_demo() else APPROVED_PROFILE)
    filled = {}
    stop = None
    for field in fields:
        code = field.get("reason_code") or classify_field(field)
        if code == "authorization_question":
            stop = build_handoff(
                "Demo Corp",
                "Software Engineering Intern",
                "authorization_question",
                extra_why=field.get("label") or field.get("name"),
            )
            break
        if code == "essay_required":
            stop = build_handoff(
                "Demo Corp",
                "Software Engineering Intern",
                "essay_required",
                extra_why=field.get("label") or field.get("name"),
            )
            break
        if code == "captcha":
            stop = build_handoff("Demo Corp", "Software Engineering Intern", "captcha")
            break
        name = field["name"].casefold()
        if "first" in name:
            filled[field["name"]] = profile["name"].split()[0]
        elif "last" in name:
            parts = profile["name"].split()
            filled[field["name"]] = parts[-1] if len(parts) > 1 else "Demo"
        elif "email" in name:
            filled[field["name"]] = profile.get("email", "demo@example.com")
        elif "school" in name or "university" in name:
            filled[field["name"]] = profile["school"]
        elif "gpa" in name:
            filled[field["name"]] = profile["gpa"]
        elif code == "routine" and field.get("type") not in ("textarea", "select"):
            continue
        elif code == "routine":
            stop = build_handoff(
                "Demo Corp",
                "Software Engineering Intern",
                "low_confidence_field",
                extra_why=field.get("label") or field.get("name"),
            )
            break
    if stop:
        return {"filled": filled, "outcome": OUTCOME_NEEDS_YOU, "handoff": stop}
    return {
        "filled": filled,
        "outcome": "ready_for_you",
        "handoff": outcome_ready("Demo Corp", "Software Engineering Intern"),
    }


def run_fixture_form(*, fixture_name="sample_form.html", use_playwright=False, trace_log=None):
    path = Path(__file__).resolve().parent.parent / "fixtures" / fixture_name
    html = path.read_text(encoding="utf-8")
    fields = read_form_fields(html)
    labeled, gemma_meta = label_fields_with_model(fields, use_gemma=True, trace_log=trace_log)
    result = fill_plan(labeled)
    result["fields"] = labeled
    if gemma_meta:
        result["gemma_meta"] = gemma_meta
    result["fixture"] = str(path)
    if use_playwright:
        result["playwright"] = _playwright_smoke(path)
    return result


def _playwright_smoke(path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"available": False}
    file_url = "file://" + pathname2url(str(path.resolve()))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(file_url, wait_until="domcontentloaded")
        names = page.evaluate(
            """() => [...document.querySelectorAll('input,textarea,select')]
              .map(el => el.name).filter(Boolean)"""
        )
        browser.close()
    return {"available": True, "field_names": names}
