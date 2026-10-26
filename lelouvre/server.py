"""Local or hosted HTTP service for the Lelouvre workspace."""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import secrets
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .store import Problem, STAGES, Store
from .scout import ScoutAgent
from .application_agent import ApplicationAgent
from .orchestrator import ApplyOrchestrator
from .today import build_today
from .internship_agent import InternshipAgent
from .evidence_bank import EvidenceBank
from .demo import demo_api_profile, demo_database_path, is_demo
from .form_reader import run_fixture_form
from .handoff_queue import HandoffQueue
from .gemma import GemmaClient
from .overnight import build_overnight_digest
from .traces import TraceLog
from .scout_fit import enrich_new_discovery_fits

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 64 * 1024


def deployment_settings():
    hosted = os.environ.get("LELOUVRE_HOSTED", "").lower() in ("1", "true", "yes")
    port = int(os.environ.get("PORT", "8765"))
    bind = "0.0.0.0" if hosted else "127.0.0.1"
    default_db = demo_database_path() if is_demo() else (ROOT / "data" / "lelouvre.sqlite3")
    database = Path(os.environ.get("LELOUVRE_DATABASE", str(default_db)))
    access = os.environ.get("LELOUVRE_ACCESS_TOKEN", "").strip()
    if hosted and not access:
        raise SystemExit("Set LELOUVRE_ACCESS_TOKEN before running Lelouvre with LELOUVRE_HOSTED=1.")
    token = access or secrets.token_hex(32)
    return hosted, bind, port, database, token


def csv_cell(value):
    value = "" if value is None else str(value)
    # Prevent user-entered spreadsheet formulas from executing in exports.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        value = "'" + value
    return value


def make_server(database, port=0, *, bind_host="127.0.0.1", hosted=False, access_token=None):
    read_only = bool(hosted and is_demo())
    if hosted and not is_demo():
        raise ValueError("Hosted mode is restricted to a fictional demo. Keep real candidate data local.")
    # Public previews must never read a persisted candidate database.
    public_demo = hosted and is_demo()
    demo_directory = tempfile.TemporaryDirectory(prefix="lelouvre-preview-") if public_demo else None
    if demo_directory:
        database = Path(demo_directory.name) / "fictional.sqlite3"
    store = Store(database)
    trace_log = TraceLog(store)
    agent = ScoutAgent(store, trace_log=trace_log)
    application_agent = ApplicationAgent(store)
    apply_orchestrator = ApplyOrchestrator(store, application_agent)
    internship_agent = InternshipAgent(store, agent, apply_orchestrator)
    evidence_bank = EvidenceBank(store)
    handoff_queue = HandoffQueue(store)
    gemma_client = GemmaClient()
    token = access_token or secrets.token_hex(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Lelouvre/0.5.2"

        def log_message(self, *_args):
            pass  # Avoid logging candidate data, URLs, or tokens.

        def send(self, status, body, content_type="application/json; charset=utf-8", filename=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def guard(self, mutation=False):
            parsed = urlsplit(self.path)
            if parsed.path == "/health" and not mutation:
                return
            if read_only and mutation:
                raise Problem("This hosted preview is read-only. Run Lelouvre locally to prepare or submit applications.", 403, "read_only_demo")
            if self.server.hosted:
                host = self.headers.get("Host", "")
                if not host:
                    raise Problem("Invalid host.", 403, "forbidden")
                origin = self.headers.get("Origin")
                if origin:
                    allowed = {f"https://{host}", f"http://{host}"}
                    if origin.rstrip("/") not in allowed:
                        raise Problem("Cross-origin requests are not allowed.", 403, "forbidden")
                if public_demo:
                    if mutation:
                        raise Problem("This is a read-only fictional preview. Run Lelouvre locally for Gemma and application preparation.", 403, "preview_read_only")
                    return
                needs_token = mutation or parsed.path.startswith("/api/")
                if needs_token and not secrets.compare_digest(self.headers.get("X-Lelouvre-Token", ""), token):
                    raise Problem("Access token required. Open Lelouvre with your saved access link.", 403, "forbidden")
                return
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in hosts:
                raise Problem("Invalid local host.", 403, "forbidden")
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                raise Problem("Cross-origin requests are not allowed.", 403, "forbidden")
            if mutation and not secrets.compare_digest(self.headers.get("X-Lelouvre-Token", ""), token):
                raise Problem("Reload Lelouvre before saving.", 403, "forbidden")

        def dispatch(self, mutation=False):
            try:
                self.guard(mutation)
                parsed = urlsplit(self.path)
                if mutation:
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise Problem("Send application/json.", 415)
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        raise Problem("Invalid request size.")
                    if not 0 < length <= MAX_BODY:
                        raise Problem("Request is empty or too large.", 413)
                    try:
                        data = json.loads(self.rfile.read(length))
                    except (ValueError, UnicodeDecodeError):
                        raise Problem("Invalid JSON.")
                    if not isinstance(data, dict):
                        raise Problem("Expected a JSON object.")
                    self.post(parsed.path, data)
                else:
                    self.get(parsed.path, parse_qs(parsed.query))
            except Problem as error:
                self.send(error.status, {"error": error.message, "code": error.code, **error.details})
            except Exception:
                logging.exception("Local request failed")
                self.send(500, {"error": "The local service could not complete this request. Your previous records are preserved.", "code": "server_error"})

        def get(self, path, query):
            if path == "/health":
                return self.send(200, {"ok": True, "name": "Lelouvre"})
            if path == "/":
                embed = "" if self.server.hosted else token
                document = (ROOT / "web" / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", embed)
                return self.send(200, document, "text/html; charset=utf-8")
            if path in ("/app.js", "/styles.css"):
                content_type = "text/javascript; charset=utf-8" if path.endswith("js") else "text/css; charset=utf-8"
                return self.send(200, (ROOT / "web" / path[1:]).read_bytes(), content_type)
            if path == "/fixtures/sample_form.html":
                fixture = ROOT / "fixtures" / "sample_form.html"
                return self.send(200, fixture.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/profile":
                return self.send(200, application_agent.profiles.get())
            if path == "/api/state":
                live_hosts = application_agent.execution_hosts - {"127.0.0.1", "localhost"}
                profile = application_agent.profiles.get()
                profile.update(authorization_answer=profile.get("work_authorized", ""), sponsorship_answer=profile.get("requires_sponsorship", ""))
                return self.send(200, {"name": "Lelouvre", "version": "0.5.2", "stages": STAGES,
                    "capabilities": {"manual_tracker": True, "live_scouting": True, "local_open_source_llm": True,
                        "llm_model": application_agent.llm.model,
                        "gemma": ({"available": False, "model_ready": False, "model": gemma_client.model, "base_url": "Local inference is available in the desktop version"} if read_only else gemma_client.status()), "application_packets": True,
                        "read_only": read_only,
                        "evidence_bank": True, "tailored_documents": True, "apply_orchestrator": True,
                        "demo_mode": is_demo(), "read_only_preview": public_demo,
                        "browser_apply": apply_orchestrator.status()["browser_available"],
                        "controlled_submissions": True, "email": False, "live_submissions_enabled": bool(live_hosts),
                        "live_execution_hosts": sorted(live_hosts), "internship_agent": True},
                    "profile": profile})
            if path == "/api/applications":
                return self.send(200, store.applications(query.get("scope", ["all"])[0]))
            if path.startswith("/api/applications/"):
                parts = path.strip("/").split("/")
                if len(parts) >= 4 and parts[-1] == "archive":
                    return self.send(200, application_agent.archive(parts[2]))
                return self.send(200, store.application(parts[-1]))
            if path == "/api/gemma":
                return self.send(200, {"available": False, "model_ready": False, "model": gemma_client.model} if read_only else gemma_client.status())
            if path == "/api/evidence":
                return self.send(200, evidence_bank.snapshot())
            if path == "/api/tasks":
                return self.send(200, store.tasks())
            if path == "/api/agent":
                return self.send(200, agent.repository.status())
            if path == "/api/apply-agent":
                return self.send(200, apply_orchestrator.status())
            if path == "/api/traces":
                kind = query.get("kind", [None])[0]
                limit = int(query.get("limit", ["40"])[0])
                return self.send(200, trace_log.list(limit=min(limit, 100), kind=kind or None))
            if path == "/api/today":
                if not read_only:
                    enrich_new_discovery_fits(store, limit=3, trace_log=trace_log)
                runs = application_agent.list()
                handoffs = handoff_queue.list_recent()
                view = build_today(store, runs, handoffs)
                scout = agent.repository.status()
                if read_only:
                    view["overnight_digest"] = {"summary": "Fictional preview only. Discovery, AI inference and application changes are disabled on this hosted demo.", "source": "rules"}
                    return self.send(200, view)
                view["overnight_digest"] = build_overnight_digest(
                    store,
                    new_roles=view["new_roles"],
                    needs_you_count=len(view["needs_you"]),
                    last_scout_at=scout.get("last_completed"),
                    trace_log=trace_log,
                )
                return self.send(200, view)
            if path == "/api/internship-agent":
                return self.send(200, internship_agent.status())
            if path == "/api/application-runs":
                return self.send(200, application_agent.list())
            if path.startswith('/api/application-runs/'):
                return self.send(200, application_agent.run(path.rsplit('/',1)[-1]))
            if path == "/api/opportunities":
                return self.send(200, agent.repository.list(query.get('scope',['all'])[0],query.get('excluded',['0'])[0]=='1'))
            if path.startswith('/api/opportunities/'):
                return self.send(200, agent.repository.detail(path.rsplit('/',1)[-1]))
            if path == "/api/export.csv":
                rows = store.applications(query.get("scope", ["all"])[0])
                fields = ("id", "type", "organization", "title", "cycle", "stage", "submitted_date", "origin", "evidence", "location", "url", "created_at", "updated_at")
                output = io.StringIO(newline="")
                writer = csv.writer(output)
                writer.writerow(fields)
                for row in rows:
                    writer.writerow([csv_cell(row[field]) for field in fields])
                return self.send(200, "\ufeff" + output.getvalue(), "text/csv; charset=utf-8", "lelouvre-applications.csv")
            raise Problem("Page not found.", 404, "not_found")

        def post(self, path, data):
            pieces = path.strip("/").split("/")
            if path == "/api/profile":
                return self.send(200, application_agent.profiles.save(data))
            if len(pieces) == 4 and pieces[:2] == ["api", "application-runs"] and pieces[3] == "answers":
                return self.send(200, application_agent.review_answers(pieces[2], data))
            if path == '/api/agent/run':
                return self.send(202,agent.start())
            if path == '/api/agent/settings':
                agent.repository.settings(data)
                return self.send(200,agent.repository.status())
            if path == '/api/apply-agent/run':
                return self.send(202, apply_orchestrator.start(data.get('trigger', 'manual'), data.get('opportunity_id')))
            if path == '/api/apply-agent/settings':
                return self.send(200, apply_orchestrator.settings(data))
            if path == "/api/gemma/chat":
                messages = data.get("messages")
                if not isinstance(messages, list):
                    raise Problem("messages must be a list of {role, content} objects.")
                content, meta = gemma_client.chat(
                    messages, temperature=float(data.get("temperature", 0)), with_meta=True
                )
                trace_log.log("gemma_chat", {"gemma_meta": meta, "message_count": len(messages)})
                return self.send(200, {"model": gemma_client.model, "content": content, "gemma_meta": meta})
            if path == "/api/demo/form-run":
                if not is_demo():
                    raise Problem("Demo form run requires LELOUVRE_DEMO=1.", 403, "demo_required")
                result = run_fixture_form(use_playwright=bool(data.get("playwright")), trace_log=trace_log)
                handoff = result.get("handoff") or {}
                handoff_queue.push("Demo Corp", "Software Engineering Intern", handoff, url="/fixtures/sample_form.html")
                return self.send(200, result)
            if path == '/api/internship-agent/run':
                return self.send(202, internship_agent.start())
            if path == '/api/internship-agent/settings':
                return self.send(200, internship_agent.settings(data))
            if len(pieces) == 4 and pieces[:2] == ['api', 'opportunities'] and pieces[3] == 'prepare':
                run = apply_orchestrator.prepare_opportunity(pieces[2])
                wrap = (run.get("packet") or {}).get("tailored") or {}
                if wrap.get("gemma_meta") or wrap.get("tailor_source"):
                    trace_log.log(
                        "gemma_tailor",
                        {
                            "run_id": run.get("id"),
                            "opportunity_id": run.get("opportunity_id"),
                            "tailor_source": wrap.get("tailor_source"),
                            "gemma_meta": wrap.get("gemma_meta"),
                            "claim_rejections": len(wrap.get("claim_rejections") or []),
                        },
                    )
                return self.send(201, run)
            if path == '/api/application-runs/prepare':
                return self.send(201, application_agent.prepare(data))
            if len(pieces) == 4 and pieces[:2] == ["api", "application-runs"] and pieces[3] == "approve":
                return self.send(200, application_agent.approve_packet(pieces[2]))
            if len(pieces)==4 and pieces[:2]==['api','application-runs'] and pieces[3]=='execute':
                settings = apply_orchestrator.status()
                if "auto_submit" in data and not isinstance(data["auto_submit"], bool):
                    raise Problem("auto_submit must be true or false.")
                auto = data.get("auto_submit", False)
                return self.send(200, application_agent.execute(pieces[2], auto_submit=auto, browser=settings["browser_submit"]))
            if path == "/api/evidence/entries":
                return self.send(201, evidence_bank.upsert_entry(data))
            if len(pieces)==4 and pieces[:2]==['api','opportunities'] and pieces[3]=='disposition':
                agent.repository.disposition(pieces[2],data.get('disposition'))
                return self.send(200,{'ok':True})
            if path == "/api/applications":
                key = self.headers.get("Idempotency-Key", "")
                if not 8 <= len(key) <= 100:
                    raise Problem("A valid save key is required.")
                record, created = store.create(data, key)
                return self.send(201 if created else 200, record)
            if len(pieces) == 4 and pieces[:2] == ["api", "applications"]:
                if pieces[3] == "update":
                    return self.send(200, store.update(pieces[2], data))
                if pieces[3] == "notes":
                    store.note(pieces[2], data)
                    return self.send(200, {"ok": True})
            if path == "/api/tasks":
                return self.send(201, store.create_task(data))
            if len(pieces) == 4 and pieces[:2] == ["api", "tasks"] and pieces[3] == "resolve":
                store.resolve_task(pieces[2])
                return self.send(200, {"ok": True})
            raise Problem("Action not found.", 404, "not_found")

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(True)

    server = ThreadingHTTPServer((bind_host, port), Handler)
    server.store = store
    server.agent = agent
    server.application_agent = application_agent
    server.apply_orchestrator = apply_orchestrator
    server.internship_agent = internship_agent
    server.read_only = read_only
    server.hosted = hosted
    server.demo_directory = demo_directory
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Run Lelouvre's application workspace")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--hosted", action="store_true", help="Listen on all interfaces (also set LELOUVRE_HOSTED=1 on Render)")
    args = parser.parse_args()
    hosted_env, bind, port_env, db_env, token = deployment_settings()
    hosted = hosted_env or args.hosted
    if hosted and not os.environ.get("LELOUVRE_ACCESS_TOKEN", "").strip():
        raise SystemExit("LELOUVRE_ACCESS_TOKEN is required for hosted mode.")
    bind = "0.0.0.0" if hosted else bind
    port = args.port if args.port is not None else port_env
    database = args.database if args.database is not None else db_env
    database.parent.mkdir(parents=True, exist_ok=True)
    server = make_server(database, port, bind_host=bind, hosted=hosted, access_token=token if hosted else None)
    if not server.read_only:
        server.agent.start_scheduler()
        server.internship_agent.start_scheduler()
    label = "hosted" if hosted else "local"
    print(f"Lelouvre ({label}): port {server.server_port}", flush=True)
    print(f"Database: {database.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.agent.close()
        server.server_close()


if __name__ == "__main__":
    main()
