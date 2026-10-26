"""Truthful application preparation, policy gating, controlled submission, and receipts."""
from __future__ import annotations

import json
import os
import hashlib
import base64
from pathlib import Path
import re
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit
from uuid import uuid4

from .handoff import (
    OUTCOME_NEEDS_YOU,
    OUTCOME_READY,
    OUTCOME_SUBMITTED,
    build_handoff,
    outcome_ready,
    outcome_submitted,
)
from .demo import demo_profile, is_demo
from .preparation import PreparationService
from .store import Problem, now
from .local_llm import OllamaProvider
from .profile_store import ProfileStore
from .forms import FormParser, AUTH_PATTERN, CONFIRMATION


def active_profile():
    return demo_profile() if is_demo() else APPROVED_PROFILE


APPROVED_PROFILE = {}

ROUTINE_FIELDS = {
    "first_name": "first_name", "last_name": "last_name", "email": "email", "phone": "phone",
    "name": "name", "full_name": "name", "school": "school", "university": "school",
    "graduation": "graduation", "graduation_date": "graduation", "gpa": "gpa",
    "work_authorized": "work_authorized", "requires_sponsorship": "requires_sponsorship",
}
REVIEW_PATTERN = re.compile(r"essay|cover.?letter|why.?us|describe|assessment|salary|demographic|disability|veteran|gender|race|ethnicity|consent|agreement", re.I)


def default_execution_hosts(override=None):
    hosts = {"127.0.0.1", "localhost"}
    if override is not None:
        hosts.update(h.casefold() for h in override if h)
        return hosts
    extra = os.environ.get("LELOUVRE_EXECUTION_HOSTS", "")
    for item in extra.split(","):
        item = item.strip().casefold()
        if item:
            hosts.add(item)
    if os.environ.get("LELOUVRE_AUTO_APPLY", "").lower() in ("1", "true", "yes"):
        hosts.update(
            {
                "boards.greenhouse.io",
                "job-boards.greenhouse.io",
                "boards.eu.greenhouse.io",
                "jobs.lever.co",
            }
        )
    return hosts


class ApplicationAgent:
    def __init__(self, store, opener=None, execution_hosts=None, llm=None):
        self.store = store; self.opener = opener or urllib.request.build_opener()
        self.execution_hosts = default_execution_hosts(execution_hosts)
        self.llm = llm or OllamaProvider()
        self.preparation = PreparationService(store)
        self.profiles = ProfileStore(store)
        with store.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS application_runs (
                    id TEXT PRIMARY KEY, opportunity_id TEXT, application_id TEXT,
                    destination TEXT NOT NULL, status TEXT NOT NULL, packet TEXT NOT NULL,
                    policy TEXT NOT NULL, receipt TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS application_archive (
                    application_id TEXT PRIMARY KEY REFERENCES applications(id),
                    resume_version TEXT NOT NULL,
                    cover_letter TEXT NOT NULL,
                    resume_json TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    receipt_json TEXT,
                    locked INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
            """)

    def prepare(self, data):
        destination = str(data.get("destination", "")).strip()
        parsed = urlsplit(destination)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise Problem("A valid application destination is required.")
        fields = data.get("fields", [])
        if not isinstance(fields, list) or not all(isinstance(item, dict) and item.get("name") for item in fields):
            raise Problem("Application fields must be a list of named fields.")
        answers, review = {}, []
        profile = self.profiles.get()
        prep = self.preparation
        field_labels = [str(field.get("label", field.get("name", ""))) for field in fields]
        for field in fields:
            name = str(field["name"])
            label = str(field.get("label", name))
            if field.get("type") in ("hidden", "submit", "button"):
                continue
            if field.get("type") in ("file", "input_file"):
                if name == "resume" and profile.get("resume_path"):
                    answers[name] = profile["resume_path"]
                elif field.get("required"):
                    review.append({"field": name, "reason": "low_confidence_field", "label": label})
                continue
            if REVIEW_PATTERN.search(label):
                reason = "essay_required" if re.search(r"essay|cover.?letter|why", label, re.I) else "review_required"
                if re.search(r"assessment", label, re.I):
                    reason = "assessment_required"
                review.append({"field": name, "reason": reason, "label": label})
                continue
            screening = prep.bank.match_screening(label)
            if (screening and screening["mode"] == "always_ask") or (AUTH_PATTERN.search(label) and not screening):
                review.append({"field": name, "reason": "authorization_question", "label": label})
                continue
            key = ROUTINE_FIELDS.get(name.casefold())
            value = screening["answer"] if screening and screening["mode"] == "auto_ok" else profile.get(key, "")
            options = field.get("options") or []
            if options and value:
                matched = [o for o in options if str(o["label"]).strip().casefold() == str(value).strip().casefold()]
                value = str(matched[0]["value"]) if len(matched) == 1 else ""
            if value and (key or screening):
                answers[name] = value
            elif field.get("required"):
                review.append({"field": name, "reason": "low_confidence_field", "label": label})
        policy = {
            "decision": "review" if review else "approved",
            "review_items": review,
            "rule": "Only approved, Auto-OK fields may be submitted automatically.",
        }
        listing = data.get("listing")
        evaluation = data.get("evaluation") or {}
        analysis = None
        if isinstance(listing, dict) and listing:
            try:
                analysis = self.llm.analyze(listing)
            except Problem as error:
                if error.code != "local_model_unavailable":
                    raise
                analysis = {
                    "role_category": "other",
                    "season": "unknown",
                    "location_status": "unknown",
                    "eligibility": "likely",
                    "summary": "Local model unavailable; deterministic rules still apply.",
                    "requirements": [],
                    "review_flags": ["Ollama unavailable — start Ollama for listing analysis."],
                    "evidence": [],
                    "provider": "none",
                    "model": "none",
                }
        tailored_packet = prep.build_packet(
            organization=(listing or {}).get("organization") or data.get("application", {}).get("organization", ""),
            title=(listing or {}).get("title") or data.get("application", {}).get("title", ""),
            location=(listing or {}).get("location") or data.get("application", {}).get("location", ""),
            description=(listing or {}).get("description", ""),
            evaluation=evaluation,
            destination=destination,
        )
        org = (listing or {}).get("organization") or data.get("application", {}).get("organization", "")
        title = (listing or {}).get("title") or data.get("application", {}).get("title", "")
        handoff = None
        outcome = OUTCOME_NEEDS_YOU if review or tailored_packet.get("verification_failures") else OUTCOME_READY
        if review:
            first = review[0]
            handoff = build_handoff(org, title, first.get("reason", "review_required"), url=destination, extra_why=first.get("label", ""))
        elif tailored_packet.get("verification_failures"):
            handoff = build_handoff(
                org,
                title,
                "review_required",
                url=destination,
                extra_why=tailored_packet["verification_failures"][0]["message"],
            )
        elif policy["decision"] == "approved":
            handoff = outcome_ready(org, title, url=destination)
        packet = {
            "answers": answers,
            "fields": fields,
            "profile_fingerprint": self.profile_fingerprint(),
            "application": data.get("application", {}),
            "analysis": analysis,
            "tailored": tailored_packet,
            "approved": False,
            "handoff": handoff,
            "outcome": outcome,
            "prepared_at": now(),
        }
        run_id, timestamp = uuid4().hex, now()
        status = "needs_review" if outcome == OUTCOME_NEEDS_YOU else "prepared"
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO application_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    data.get("opportunity_id"),
                    None,
                    destination,
                    status,
                    json.dumps(packet),
                    json.dumps(policy),
                    None,
                    timestamp,
                    timestamp,
                ),
            )
        return self.enrich_run(self.run(run_id))

    def approve_packet(self, run_id):
        run = self.run(run_id)
        previous_packet = json.dumps(run["packet"])
        packet = run["packet"]
        if run["status"] in ("submitted", "submitting", "receipt_unconfirmed"):
            raise Problem("This submission is locked. Check the receipt first.", 409, "submission_locked")
        if packet.get("profile_fingerprint") != self.profile_fingerprint():
            raise Problem("Your profile or evidence changed. Prepare this application again.", 409, "packet_stale")
        if not packet or not packet.get("tailored"):
            raise Problem("No tailored documents to approve.", 409, "no_packet")
        try:
            packet = self.preparation.approve_packet(packet["tailored"])
        except ValueError as error:
            raise Problem(str(error), 409, "verification_failed")
        full = dict(run["packet"])
        full["tailored"] = packet
        full["approved"] = True
        full["profile_fingerprint"] = self.profile_fingerprint()
        attachment = full.get("answers", {}).get("resume")
        if attachment:
            content = Path(attachment).read_bytes()
            full["resume_attachment"] = {"filename": Path(attachment).name, "sha256": hashlib.sha256(content).hexdigest(), "base64": base64.b64encode(content).decode("ascii")}
        org = full.get("application", {}).get("organization", "")
        title = full.get("application", {}).get("title", "")
        ready = run["policy"]["decision"] == "approved"
        full["handoff"] = outcome_ready(org, title, url=run["destination"]) if ready else build_handoff(org, title, "review_required", url=run["destination"])
        full["outcome"] = OUTCOME_READY if ready else OUTCOME_NEEDS_YOU
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE application_runs SET packet=?, status=?, updated_at=? WHERE id=? AND packet=? AND status NOT IN ('submitted','submitting','receipt_unconfirmed')",
                (json.dumps(full), "prepared" if ready else "needs_review", now(), run_id, previous_packet),
            )
        return self.enrich_run(self.run(run_id))

    def inspect(self, destination):
        from .browser_executor import BrowserExecutor
        executor = BrowserExecutor(self.profiles.get())
        if (urlsplit(destination).hostname or "") not in {"localhost", "127.0.0.1"} and executor.available():
            return executor.inspect(destination)
        from .verify import classify_apply_url
        verified = classify_apply_url(destination)
        if verified and verified["platform"] == "greenhouse":
            board = urllib.parse.quote(verified["board"], safe="")
            url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{verified['external_job_id']}?questions=true"
            with self.opener.open(url, timeout=20) as response:
                data = json.loads(response.read(2 * 1024 * 1024))
            fields = []
            for question in data.get("questions", []):
                # File and pasted-text alternatives represent one resume question.
                alternatives = question.get("fields", [])
                for f in alternatives[:1]:
                    fields.append({"name": f["name"], "type": "file" if f["type"] == "input_file" else f["type"],
                                   "label": question["label"], "required": question.get("required", False),
                                   "options": [{"label": str(o["label"]), "value": str(o["value"])} for o in f.get("values", [])]})
            if not fields:
                raise Problem("Employer did not return application questions.", 409, "unfamiliar_form")
            return {"fields": fields}
        with self.opener.open(destination, timeout=20) as response:
            body = response.read(1024 * 1024).decode("utf-8", "replace")
        parser = FormParser(); parser.feed(body); parser.close()
        if not parser.fields:
            raise Problem("No application form could be inspected.", 409, "unfamiliar_form")
        return {"action": urllib.parse.urljoin(destination, parser.action or destination), "method": parser.method,
                "fields": parser.fields}

    def execute(self, run_id, *, auto_submit=False, browser=False):
        run = self.run(run_id)
        if run["status"] in ("submitted", "submitting", "receipt_unconfirmed"):
            return run
        packet = run["packet"] or {}
        meta = packet.get("application") or {}
        org, title = meta.get("organization", ""), meta.get("title", "")

        def save_handoff(code, **kwargs):
            handoff = build_handoff(org, title, code, url=run["destination"], **kwargs)
            packet["handoff"] = handoff
            packet["outcome"] = OUTCOME_NEEDS_YOU
            self._save_packet(run_id, packet, "needs_review")
            return self.enrich_run(self.run(run_id))

        if packet.get("profile_fingerprint") != self.profile_fingerprint():
            packet["approved"] = False
            return save_handoff("packet_not_approved", extra_why="Your profile or resume changed. Prepare and review again.")
        if not packet.get("approved"):
            return save_handoff("packet_not_approved")
        if run["policy"]["decision"] != "approved":
            return save_handoff("review_required")
        host = (urlsplit(run["destination"]).hostname or "").casefold()
        if host not in self.execution_hosts:
            return save_handoff("host_not_enabled")
        if not auto_submit:
            packet["handoff"] = outcome_ready(org, title, url=run["destination"])
            packet["outcome"] = OUTCOME_READY
            self._save_packet(run_id, packet, "prepared")
            return self.enrich_run(self.run(run_id))
        if host not in {"localhost", "127.0.0.1"} or browser:
            return self._execute_browser(run)
        try:
            form = self.inspect(run["destination"])
        except Exception:
            return save_handoff("unfamiliar_form")
        if re.search(r"captcha|hcaptcha|recaptcha", form.get("action", ""), re.I):
            return save_handoff("captcha")
        for field in form["fields"]:
            label = field.get("label", field.get("name", ""))
            if REVIEW_PATTERN.search(label) and field["name"] not in packet.get("reviewed_fields", []):
                code = "essay_required" if re.search(r"essay|cover", label, re.I) else "assessment_required"
                return save_handoff(code, extra_why=label)
            match = self.preparation.bank.match_screening(label)
            if match and match["mode"] == "always_ask" and field["name"] not in packet.get("reviewed_fields", []):
                return save_handoff("authorization_question", extra_why=label)
        unknown_required = [
            field["name"]
            for field in form["fields"]
            if field["required"] and field["name"] not in run["packet"]["answers"]
        ]
        if unknown_required:
            return save_handoff("low_confidence_field", extra_why=f"Missing answers for: {', '.join(unknown_required[:3])}")
        if urlsplit(form["action"]).hostname != urlsplit(run["destination"]).hostname:
            return save_handoff("unfamiliar_form")
        if not self._claim_submission(run):
            return self.run(run_id)
        values = {f["name"]: f.get("value", "") for f in form["fields"] if f.get("type") == "hidden"}
        values.update(packet["answers"])
        payload = urllib.parse.urlencode(values, doseq=True).encode()
        request = urllib.request.Request(form["action"], data=payload, method="POST")
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read(512 * 1024).decode("utf-8", "replace")
                final_url, status = response.geturl(), response.status
        except Exception:
            self._status(run_id, "receipt_unconfirmed", receipt={"confirmed": False, "submitted": True, "evidence": "Network failure after submission started. Check the employer before retrying."})
            return self.run(run_id)
        if re.search(r"captcha|hcaptcha|recaptcha", body, re.I):
            self._status(run_id, "receipt_unconfirmed", receipt={"confirmed": False, "submitted": True, "evidence": "Employer returned a CAPTCHA. Check the application before retrying."})
            return self.run(run_id)
        confirmed = status < 400 and bool(
            CONFIRMATION.search(body)
        )
        receipt = {
            "confirmed": confirmed,
            "submitted": True,
            "http_status": status,
            "final_url": final_url,
            "evidence": "Confirmation language found." if confirmed else "Submission unknown — please confirm.",
            "captured_at": now(),
        }
        packet["handoff"] = outcome_submitted(org, title, evidence=receipt["evidence"])
        packet["outcome"] = OUTCOME_SUBMITTED if confirmed else OUTCOME_NEEDS_YOU
        if not confirmed:
            packet["handoff"] = build_handoff(
                org,
                title,
                "review_required",
                url=run["destination"],
                extra_why="I couldn't confirm the submission went through.",
            )
        new_status = "submitted" if confirmed else "receipt_unconfirmed"
        self._status(run_id, new_status, receipt=receipt)
        self._save_packet(run_id, packet, new_status)
        if confirmed:
            self._log_application(run_id)
        return self.enrich_run(self.run(run_id))

    def profile_fingerprint(self):
        profile = self.profiles.get()
        path = profile.get("resume_path")
        digest = ""
        if path:
            try:
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            except OSError:
                digest = "missing"
        return hashlib.sha256((json.dumps(profile, sort_keys=True) + digest + json.dumps(self.preparation.bank.snapshot(), sort_keys=True)).encode()).hexdigest()

    def review_answers(self, run_id, data):
        run = self.run(run_id)
        if run["status"] in ("submitted", "submitting", "receipt_unconfirmed"):
            raise Problem("This submission is locked. Check its receipt first.", 409, "submission_locked")
        packet = run["packet"]
        previous_packet = json.dumps(packet)
        fields = {f["name"]: f for f in packet.get("fields", []) if f.get("type") not in ("hidden", "file", "input_file", "submit", "button")}
        supplied = data.get("answers", {})
        if not isinstance(supplied, dict) or set(supplied) - set(fields):
            raise Problem("Answers must match this application's questions.")
        for name, answer in supplied.items():
            field = fields[name]
            values = answer if isinstance(answer, list) else [answer]
            if not all(isinstance(v, str) and len(v) <= 10000 for v in values):
                raise Problem("Answers must be text.")
            options = {str(o["value"]) for o in field.get("options", [])}
            if options and any(v not in options for v in values if v):
                raise Problem("Choose one of the listed answers.")
            packet["answers"][name] = answer
        review = []
        for field in packet.get("fields", []):
            if field.get("required") and field.get("type") not in ("hidden", "submit", "button") and not packet["answers"].get(field["name"]):
                review.append({"field": field["name"], "label": field.get("label", field["name"]), "reason": "low_confidence_field"})
        # Optional sensitive questions also need explicit review or omission.
        for item in run["policy"].get("review_items", []):
            if item["field"] not in supplied and item["field"] not in {r["field"] for r in review}:
                review.append(item)
        policy = {**run["policy"], "review_items": review, "decision": "review" if review else "approved"}
        packet["approved"] = False
        packet["reviewed_fields"] = sorted(set(packet.get("reviewed_fields", [])) | set(supplied))
        with self.store.connect() as c:
            c.execute("UPDATE application_runs SET packet=?,policy=?,status='needs_review',updated_at=? WHERE id=? AND packet=? AND status NOT IN ('submitted','submitting','receipt_unconfirmed')",
                      (json.dumps(packet), json.dumps(policy), now(), run_id, previous_packet))
        return self.run(run_id)

    def _claim_submission(self, run):
        # Serialize the last check across concurrent requests and separate runs.
        canonical = run["destination"].split("?", 1)[0].replace("https://boards.greenhouse.io/", "https://job-boards.greenhouse.io/")
        fingerprint = self.profile_fingerprint()
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute("SELECT packet,policy FROM application_runs WHERE id=?", (run["id"],)).fetchone()
            current_packet = json.loads(current["packet"])
            if current_packet != run["packet"] or not current_packet.get("approved") or current_packet.get("profile_fingerprint") != fingerprint or json.loads(current["policy"])["decision"] != "approved":
                raise Problem("This packet needs review before submission.", 409, "packet_not_approved")
            rows = c.execute("SELECT id,destination,status FROM application_runs WHERE status IN ('submitted','submitting','receipt_unconfirmed')").fetchall()
            for row in rows:
                other = row["destination"].split("?", 1)[0].replace("https://boards.greenhouse.io/", "https://job-boards.greenhouse.io/")
                if other == canonical:
                    if row["id"] == run["id"]:
                        return False
                    raise Problem("This role was already submitted or has an uncertain receipt. Check it before retrying.", 409, "already_applied")
            return c.execute("UPDATE application_runs SET status='submitting',updated_at=? WHERE id=? AND status NOT IN ('submitted','submitting','receipt_unconfirmed')", (now(), run["id"])).rowcount == 1

    def _execute_browser(self, run):
        from .browser_executor import BrowserExecutor
        executor = BrowserExecutor(self.profiles.get(), submit=True)
        # No submission can occur until preflight passes and the durable claim succeeds.
        try:
            receipt = executor.run(run["destination"], run["packet"]["answers"],
                                   before_submit=lambda: self._claim_submission(run),
                                   expected_fields=run["packet"].get("fields", []))
        except Problem as error:
            if self.run(run["id"])["status"] == "submitting":
                self._status(run["id"], "receipt_unconfirmed", receipt={"confirmed": False, "submitted": True, "evidence": error.message})
                return self.run(run["id"])
            raise
        except Exception:
            if self.run(run["id"])["status"] == "submitting":
                self._status(run["id"], "receipt_unconfirmed", receipt={"confirmed": False, "submitted": True, "evidence": "Browser interrupted after submission started. Check employer confirmation."})
                return self.run(run["id"])
            raise Problem("The browser could not open this application. Check browser installation and try again.", 503, "browser_unavailable")
        if not receipt.get("submitted") and self.run(run["id"])["status"] in ("submitted", "submitting", "receipt_unconfirmed"):
            return self.run(run["id"])
        packet = run["packet"]
        confirmed = receipt.get("confirmed", False)
        status = "submitted" if confirmed else "receipt_unconfirmed" if receipt.get("submitted") else "needs_review"
        packet["outcome"] = OUTCOME_SUBMITTED if confirmed else OUTCOME_NEEDS_YOU
        packet["handoff"] = outcome_submitted("", "", evidence=receipt.get("evidence", "")) if confirmed else build_handoff("", "", "review_required", url=run["destination"], extra_why=receipt.get("evidence", "Check the application."))
        self._status(run["id"], status, receipt=receipt)
        self._save_packet(run["id"], packet, status)
        if confirmed:
            self._log_application(run["id"])
        return self.run(run["id"])

    def _save_packet(self, run_id, packet, status):
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE application_runs SET packet=?, status=?, updated_at=? WHERE id=?",
                (json.dumps(packet), status, now(), run_id),
            )

    def _log_application(self, run_id):
        run = self.run(run_id); packet = run["packet"]
        meta = packet.get("application", {})
        if not all(meta.get(k) for k in ("organization", "title", "cycle")): return
        record = {"type":"internship", "organization":meta["organization"], "title":meta["title"], "cycle":meta["cycle"],
                  "stage":"Applied", "submitted_date":date.today().isoformat(), "url":run["destination"], "location":meta.get("location", "")}
        application, _ = self.store.create(record, "agent-" + run_id)
        tailored_wrap = packet.get("tailored") or {}
        inner = tailored_wrap.get("tailored") or tailored_wrap
        resume_doc = dict(inner.get("resume") or {})
        if packet.get("resume_attachment"):
            resume_doc["attachment"] = packet["resume_attachment"]
        resume_doc["suggestions_only"] = True
        cover = inner.get("cover_letter") or {}
        with self.store.connect() as connection:
            connection.execute("UPDATE applications SET origin='agent',evidence='verified_receipt' WHERE id=?", (application["id"],))
            connection.execute("UPDATE application_runs SET application_id=? WHERE id=?", (application["id"], run_id))
            connection.execute(
                """INSERT OR REPLACE INTO application_archive
                   (application_id,resume_version,cover_letter,resume_json,answers_json,receipt_json,locked,created_at)
                   VALUES (?,?,?,?,?,?,1,?)""",
                (
                    application["id"],
                    f"{resume_doc.get('variant','')}-v{resume_doc.get('version','')}",
                    "\n\n".join(cover.get("paragraphs") or []),
                    json.dumps(resume_doc),
                    json.dumps(packet.get("answers") or {}),
                    json.dumps(run.get("receipt") or {}),
                    now(),
                ),
            )

    def enrich_run(self, run):
        packet = run.get("packet") or {}
        meta = packet.get("application") or {}
        org, title = meta.get("organization", ""), meta.get("title", "")
        if run.get("status") in ("submitting", "receipt_unconfirmed"):
            run["outcome"] = OUTCOME_NEEDS_YOU
            run["handoff"] = build_handoff(org, title, "review_required", url=run["destination"], extra_why=(run.get("receipt") or {}).get("evidence", "Submission started. Check the employer before retrying."))
        elif run.get("status") == "submitted":
            run["outcome"] = OUTCOME_SUBMITTED
            run["handoff"] = outcome_submitted(org, title, evidence=(run.get("receipt") or {}).get("evidence", ""))
        elif packet.get("handoff"):
            run["outcome"] = packet.get("outcome") or packet["handoff"].get("outcome")
            run["handoff"] = packet["handoff"]
        else:
            from .preparation import attach_outcome_to_run

            outcome, handoff = attach_outcome_to_run(run, org, title)
            if outcome:
                run["outcome"] = outcome
                run["handoff"] = handoff
        return run

    def _status(self, run_id, status, policy=None, receipt=None):
        with self.store.connect() as connection:
            if policy is not None: connection.execute("UPDATE application_runs SET status=?,policy=?,updated_at=? WHERE id=?", (status,json.dumps(policy),now(),run_id))
            else: connection.execute("UPDATE application_runs SET status=?,receipt=?,updated_at=? WHERE id=?", (status,json.dumps(receipt),now(),run_id))

    def run(self, run_id):
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM application_runs WHERE id=?", (run_id,)).fetchone()
            if row is None: raise Problem("Application run not found.", 404, "not_found")
            result = dict(row)
        for key in ("packet", "policy", "receipt"):
            result[key] = json.loads(result[key]) if result[key] else None
        return self.enrich_run(result)

    def list(self):
        with self.store.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM application_runs ORDER BY created_at DESC")]
        return [self.run(run_id) for run_id in ids]

    def archive(self, application_id):
        with self.store.connect() as connection:
            row = connection.execute("SELECT * FROM application_archive WHERE application_id=?", (application_id,)).fetchone()
        if row is None:
            raise Problem("No submitted materials archived for this application.", 404, "not_found")
        data = dict(row)
        data["resume_json"] = json.loads(data["resume_json"])
        data["answers_json"] = json.loads(data["answers_json"])
        data["receipt_json"] = json.loads(data["receipt_json"]) if data["receipt_json"] else None
        return data
