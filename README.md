# Lelouvre

Local internship/scholarship tracker and first read-only scouting agent. Python 3.10+; no third-party packages required.

## Current milestone

- Save manually submitted internships and scholarships in SQLite.
- Separate application types, cycles, stages, and user-reported submission evidence.
- Detect duplicates, including uncertain cycle matches; make repeated application saves idempotent.
- Preserve stage/date correction history, add notes, and track dated tasks.
- Filter/search records, switch internship/scholarship scope, and export application fields as CSV.
- Keep edits from stale windows from silently overwriting newer progress.

The application tracker starts empty; prototype samples are not imported. The read-only scouting engine can populate a separate opportunities inbox from the configured sources. Email delivery and resume text extraction are not implemented. Reviewed browser submissions support Greenhouse/Lever form controls, including uploads, dropdowns and checkboxes, with conservative handoffs for unsupported controls or challenges.

## Scouting agent (0.2)

Open **Scouting agent** to run a check, inspect evidence and source health, pause individual sources, or enable six-hour scheduled checks. Scheduled checks run only while the local server is running; no Windows startup task or cloud service is installed. On this workspace the schedule was enabled after the first live checks. Settings persist in SQLite.

Connected adapters:

- Cloudflare and Datadog public Greenhouse job feeds. Relevant internship listings are stored by source/requisition ID, scored with transparent rules, and kept separate from submitted applications. Official career pages: https://www.cloudflare.com/careers/jobs/ and https://careers.datadoghq.com/.
- ISACA Foundation and Center for Cyber Safety and Education scholarship program page watchers. Pages/changes are leads, not verified individual award openings. Source availability depends on public page content; script-only or blocked pages are reported as failures.

The initial live check read 867 source entries and stored eight relevant records across three readable sources; one scholarship source required follow-up. Those are discovered records, not eight verified eligible openings. Rules deliberately retain unknown season/location/eligibility information. Out-of-scope locations and doctoral titles can be inspected using **Include excluded**. There is no claim of comprehensive coverage.

Discovery is driven by role category (software engineering, cybersecurity/cloud security, and undergraduate research), season, and location. Resume overlap is explanatory evidence only: it never gates discovery and never changes a role's priority. Additional internship sources (0.3): **SimplifyJobs Summer 2027 GitHub list** (verified Greenhouse/Lever links), **r/internships**, and **r/csMajors** (community leads until an ATS URL is verified). LinkedIn, Indeed, and X still require future session adapters.

## Apply agent (0.3)

Open **Apply agent** for the full pipeline: **verify ATS URL → Ollama listing analysis → deterministic policy gate → prepare packet → optional controlled execute** (HTTP or Playwright on Greenhouse/Lever). Accuracy gates block auto-execute unless Summer 2027 is confirmed, the apply URL is verified, policy approves all fields, and analysis raises no high-risk flags. Duplicate applications in your tracker are skipped.

## Local Gemma (0.5.2 — Hacktoberfest / open-source AI)

Lelouvre calls **Gemma through Ollama** directly (`lelouvre/gemma.py`), not a hosted API. Gemma is used in bounded, auditable places:

| Step | What Gemma does | Safety |
|------|-------------------|--------|
| **Discover fit** | One cached sentence per new role (`scout_fit.py`) | Facts from rule-based evaluation only |
| **Prepare** | JSON résumé bullets with `source_id` | `claim_check.py` rejects unsupported claims |
| **Today digest** | Two-sentence “while you were away” summary | Falls back to rules if Ollama is down |
| **Demo form** | Optional field labels (`LELOUVRE_FORM_GEMMA=1`) | Auth/essay/captcha always hand off to you |

Traces: `GET /api/traces` (optional `?kind=gemma_tailor`). Activity shows recent calls with latency and token counts when Ollama returns them.

```powershell
ollama pull gemma3:4b
$env:LELOUVRE_GEMMA_MODEL = "gemma3:4b"
$env:LELOUVRE_GEMMA_URL = "http://127.0.0.1:11434"
python -m lelouvre.server
```

Demo without Ollama (CI / Render): `LELOUVRE_TAILOR_OFFLINE=1` or use `Start-Lelouvre-Demo.ps1`. Compare models locally: `python scripts/compare_models.py`.

Listing analysis uses the same stack (`LELOUVRE_GEMMA_MODEL` or legacy `LELOUVRE_OLLAMA_MODEL`, default `gemma3:4b`). Live employer submit stays off localhost unless you set allowlisted hosts:

```powershell
$env:LELOUVRE_EXECUTION_HOSTS = "boards.greenhouse.io,job-boards.greenhouse.io,jobs.lever.co"
python -m lelouvre.server
```

Optional browser submit: `pip install -r requirements-playwright.txt` then `playwright install chromium`, enable **Browser submit** on the Apply agent page.

Failed fetches retain previous results. A complete successful feed may mark an absent listing **No longer in feed**, which is not a confirmed application rejection. First seen is discovery time, not publication time. A changed page is not an opening announcement. Network calls are HTTPS, destination-allowlisted, bounded in size/time, and read-only. Schema version 2 adds scouting records without deleting the original tracker.

One-off check (use one local service/runner per database):

```powershell
python -m lelouvre.scout
```

API reference used: https://docs.greenhouse.io/job-board. Public listing access does not grant application-submission API access.

## Run

On Windows, double-click **Open Lelouvre.cmd** in this folder. It starts the local service in a hidden background process if needed and opens your default browser. It can be used outside ChatGPT/Codex. Closing the browser does not stop the service; shutting down or restarting Windows does. This launcher does not install automatic Windows startup. Run it again after restarting your computer. Logs go to `data/server.out.log` and `data/server.err.log`.

The launcher uses the existing bundled Python when available, otherwise `python` from PATH. Lelouvre itself does not require an active ChatGPT session. It remains a local app: another computer or phone cannot use this loopback URL, and six-hour monitoring requires the computer to be awake with the service running.

From this project folder:

```powershell
python -m lelouvre.server
```

Open http://127.0.0.1:8765 in a browser. The service binds only to the local loopback address. Keep the process running while using the dashboard; Ctrl+C stops it. Saved records remain on disk. Restarting changes the request token, so reload an older browser tab before saving.

If Python is not on PATH, the bundled runtime available in this environment is:

```powershell
& '.venv\Scripts\python.exe' -m lelouvre.server
```

Alternate port/database:

```powershell
python -m lelouvre.server --port 8766 --database .tmp/test.sqlite3
```

## Data and backup

The default database is `data/lelouvre.sqlite3` within the project, excluded from version control. This is a local single-user development service, not an internet-hosted deployment. Database files are not encrypted by this app. OS and folder access control protect this milestone; browser-origin checks and a per-process request token protect write requests from unrelated web pages. Any local process with filesystem access can read the database. The project folder may follow its existing device sync settings.

For a full backup, stop the service and copy the SQLite file to a protected location. Test restoration on a copy. CSV exports cover application fields only; they do not include full notes, events, or tasks. A backup/restore interface, encrypted storage, and production authentication are future work.

Draft manual-entry forms are retained in this browser tab's session storage until saved or cleared. The canonical records and history are in SQLite. Screenshot/email extraction is unavailable; links are references and are not fetched. History records when edits were entered, while a submitted date records the date reported by the user. All displayed event timestamps use America/New_York.

## Validate

```powershell
python -m unittest discover -s tests -v
```

Tests use temporary databases and cover persistence, concurrent duplicates, idempotency, scholarship cycles, state validation, stale edits, notes/tasks, CSV formula escaping, origin/token checks, HTTP behavior, targeting rules, scouting deduplication, snapshots, disappearance/relisting, and source failure retention. Scouting unit tests use fixtures, not external network calls.

For browser verification, start a separate server on port 8766 with a disposable test database as above. Run `tests/browser-check.cjs` using Node and an available Playwright installation (`PLAYWRIGHT_MODULE` may specify its module directory). It creates QA records only on port 8766 and checks saves, reloads, history, tasks, duplicates, filters, narrow layouts, and conflicting edits. Never run that server with the real application database. The initial milestone passed all 12 Python tests and the browser walkthrough.

Version 0.2 passed 26 Python tests. `tests/scout-browser.cjs` performs a read-only browser walkthrough against port 8765: coverage/run history, scope filtering, scholarship evidence/review labels, and narrow layout. It does not trigger a new scan or change application records.

## Architecture

See SYSTEM_DESIGN.md, ARCHITECTURE.md, SCREEN_SPEC.md, and SCHOLARSHIPS.md. The current schema is the tracker and initial scouting subset of that target architecture. `prototype/lelouvre-ui.js` is the earlier sample-only interface and is not loaded by the working app.

## Submission workflow repairs (0.5.1)

1. Open **My Profile**, enter contact details and the full path to an existing PDF/DOCX resume, then save. The attachment is sent as-is; tailored bullets are suggestions and do not rewrite that file.
2. Save a role in **Discover**, then **Get this application ready**. Read and complete **Application answers**, save reviewed answers, then **Approve changes**. Verification failures cannot be bypassed by approval.
3. **Submit for me** requests one submission explicitly. Real employer submissions use the browser executor. Unanswered required questions, changed forms, CAPTCHA, unsupported controls and incomplete uploads stop execution.
4. For a reviewed queue, enable **Auto-execute** and **Auto-when-safe**, then run **Prepare saved roles**. Existing packets are reused while profile/evidence/posting content remains unchanged. Each run attempts at most five applications. New packets still require review.
5. Counts record confirmed employer receipts, not merely execution calls. Interrupted or uncertain submissions are locked against automatic retry; inspect the employer before taking further action.

The launcher prefers `.venv/Scripts/python.exe`. Browser setup in PowerShell:

```powershell
python -m venv .venv
python -m pip --python .venv/Scripts/python.exe install -r requirements-playwright.txt
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD '.venv/browsers'
.venv/Scripts/python.exe -m playwright install chromium
```

Run `Open Lelouvre.cmd` to load version 0.5.2. The launcher replaces an older Lelouvre server, but refuses to stop another app using the same port. Discovery includes direct Stripe, MongoDB, Robinhood and Duolingo feeds in addition to the existing sources. Community feeds may still be blocked by their providers; source health reports those failures.

**Public demo deploy:** `render.yaml` runs demo mode with `LELOUVRE_HOSTED=1` and generated `LELOUVRE_ACCESS_TOKEN` (read-only hosted UI; no Ollama on Render). License: Apache-2.0 (`LICENSE`).

Run the regression suite with `.venv/Scripts/python.exe -m unittest discover -s tests -q`. Browser tests use local disposable forms, never employer submissions.
