# Lelouvre

**Let internship preparation happen at your pace.**

Lelouvre is a local internship assistant that discovers relevant roles, uses **Gemma through Ollama** to draft résumé bullets from your recorded experience, and helps you prepare applications with fewer repetitive steps.

It shows the evidence behind its suggestions, checks generated claims, and hands questions needing your judgment back to you.

Built for the Hacktoberfest **“Slow and Steady”** theme: automate repetitive preparation, then review what matters.

## What it does

- **Finds opportunities:** Reads public employer feeds and community sources, removes duplicates, and evaluates roles against explicit targeting rules.
- **Explains fit:** Uses local Gemma to write short explanations grounded in listing details and recorded skills.
- **Prepares materials:** Generates structured résumé bullets linked to entries in your evidence bank.
- **Checks claims:** Rejects missing evidence references and certain unsupported numbers or tool names.
- **Supports review:** Shows suggested changes and lets you review application answers before approval.
- **Handles compatible forms:** Uses browser automation for uploads, text fields, dropdowns, and checkboxes on supported Greenhouse and Lever forms.
- **Tracks outcomes:** Records confirmed submissions, preserves application materials, and explains when you need to finish an application yourself.
- **Summarizes activity:** Displays a “While you were away” digest and recent Gemma traces.

The manual tracker also supports scholarships, notes, stages, tasks, and CSV export. Automated preparation focuses on internships.

## Why local, open-weight AI?

Internship applications involve personal information and repeated writing. Lelouvre uses a local model so résumé evidence and generation prompts can stay on your machine during inference.

Gemma runs through Ollama. You can select a different installed model, inspect the prompts and rules, and change the workflow without depending on a paid inference API.

The model handles language tasks. Code controls targeting, validation, approval, and submission decisions.

**Local inference does not make the entire application offline.** Discovery needs access to public sources, and submitting an application sends your approved information to the employer.

## Where Gemma is used

| Feature                  | Model contribution                                 | Controls                                                |
| ------------------------ | -------------------------------------------------- | ------------------------------------------------------- |
| Listing analysis         | Summarizes requirements and flags uncertainty      | Deterministic targeting and submission gates            |
| Discovery fit            | Writes a short explanation for a role              | Supplied listing and evaluation facts                   |
| Résumé tailoring         | Produces structured bullets with evidence IDs      | Output validation and claim checks                      |
| Today digest             | Summarizes available roles and outstanding actions | Supplied activity counts and facts                      |
| Demo form classification | Suggests field categories                          | Authorization, essay, and CAPTCHA rules take precedence |

The interface displays the tailoring source and available model metadata. **Settings & Activity** shows recent traces, including token counts when Ollama supplies them.

Fallback output is labeled separately from Gemma output.

## Application workflow

1. **Complete My Profile.** Enter contact details and the full path to an existing PDF or DOCX résumé.
2. **Find and save a role.** Review its location, season, requirements, and blockers.
3. **Prepare the application.** Generate suggestions and inspect their evidence references.
4. **Review answers and documents.** Complete unresolved questions, save the answers, and approve the packet.
5. **Submit or finish manually.** Compatible applications can be submitted through the browser executor. Other applications produce a handoff explaining what needs attention.

**Your selected résumé file is uploaded as-is.** Suggested bullets do not automatically rewrite that file. Incorporate any desired changes into your résumé before attaching and approving it.

## Submission controls

Automatic execution requires an approved packet, approved answers, an enabled employer host, and passing eligibility and accuracy checks.

For a reviewed queue, enable **Auto-execute** and **Auto-when-safe** in Settings & Activity, then run **Prepare saved roles**.

Each pipeline run attempts at most five applications. Newly prepared packets still require review.

Changes to profile information, evidence, résumé contents, or posting details can require another review. Confirmed and uncertain submissions are protected against automatic retries.

The main outcomes are:

| Outcome           | Meaning                                                                     |
| ----------------- | --------------------------------------------------------------------------- |
| **Submitted**     | Employer confirmation was detected                                          |
| **Ready for you** | Materials are prepared; your next action is required                        |
| **Needs you**     | A question, unsupported control, challenge, or uncertainty stopped progress |

An execution attempt is not counted as a confirmed submission.

## Run locally

### Requirements

- Python 3.10+
- Ollama and a downloaded model for local AI features
- Playwright and Chromium for browser automation
- Internet access for discovery and employer applications

The basic tracker uses Python’s standard library and SQLite.

### 1. Clone the repository

```powershell
git clone https://github.com/beryl-ghany/lelouvre.git
cd lelouvre
python -m venv .venv
```

### 2. Set up Gemma

Install and open [Ollama](https://ollama.com), then run:

```powershell
ollama pull gemma3:4b
$env:LELOUVRE_GEMMA_MODEL = "gemma3:4b"
$env:LELOUVRE_GEMMA_URL = "http://127.0.0.1:11434"
```

You can substitute another compatible installed model tag. Restart Lelouvre after changing its environment variables.

### 3. Install browser support

```powershell
python -m pip --python .venv/Scripts/python.exe install -r requirements-playwright.txt
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD '.venv/browsers'
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 4. Start Lelouvre

```powershell
.\.venv\Scripts\python.exe -m lelouvre.server
```

Open [Lelouvre locally](http://127.0.0.1:8765).

On Windows, you can also use **Open Lelouvre.cmd**. The launcher prefers the project’s virtual environment and starts the service in the background.

The computer must remain awake and the server must remain running for scheduled discovery.

### 5. Enable employer execution when ready

When starting the server manually, explicitly configure the supported execution hosts:

```powershell
$env:LELOUVRE_EXECUTION_HOSTS = "boards.greenhouse.io,job-boards.greenhouse.io,jobs.lever.co"
.\.venv\Scripts\python.exe -m lelouvre.server
```

Host configuration alone does not approve packets or bypass submission gates.

## Demo mode

Demo mode uses a fictional profile and evidence bank. It can run with real local Gemma inference or with deterministic fallback output.

To run a separate demo server:

```powershell
$env:LELOUVRE_DEMO = "1"
$env:LELOUVRE_DATABASE = Join-Path $PWD 'data\lelouvre-demo.sqlite3'
$env:LELOUVRE_GEMMA_MODEL = "gemma3:4b"
Remove-Item Env:LELOUVRE_TAILOR_OFFLINE -ErrorAction SilentlyContinue

.\.venv\Scripts\python.exe -m lelouvre.server --port 8766
```

Open [the local demo](http://127.0.0.1:8766).

Use a separate PowerShell window for demo mode so its environment settings stay separate from your real workspace.

For a demo without model inference, set this before starting:

```powershell
$env:LELOUVRE_TAILOR_OFFLINE = "1"
```

The demo form stops at an authorization question and does not submit to an employer.

### Suggested walkthrough

1. Show the fictional evidence bank.
2. Discover a role and inspect its fit explanation.
3. Prepare materials and show Gemma-generated bullets with evidence IDs.
4. Open Settings & Activity to inspect the corresponding trace.
5. Run the demo form and show its handoff.

A Gemma ping demonstrates connectivity. A successful tailoring trace demonstrates the model performing useful work.

## Discovery sources

Configured sources include:

- Cloudflare
- Datadog
- Stripe
- MongoDB
- Robinhood
- Duolingo
- Simplify’s Summer 2027 internship list
- Selected Reddit communities
- Scholarship program page watchers

Sources can become unavailable, block requests, or change their format. Lelouvre reports source health and retains previous results when a fetch fails.

A community entry is a lead. A recognized ATS URL is not proof of eligibility or a complete application.

## Project structure

```text
lelouvre/
  gemma.py              Local Ollama client
  scout.py              Discovery and targeting
  scout_fit.py          Gemma fit explanations
  evidence_bank.py      Recorded experience and screening rules
  preparation.py        Packet preparation and validation
  claim_check.py        Deterministic bullet checks
  application_agent.py  Approval, execution, receipts, archive
  browser_executor.py   Supported browser form handling
  orchestrator.py       Reviewed application queue
  overnight.py          Today digest
  traces.py             Local trace storage
  server.py             HTTP service

web/                    Browser interface
fixtures/               Demo forms
tests/                  Automated tests
scripts/                Model-comparison utilities
```

## Validation

Run the test suite:

```powershell
$env:LELOUVRE_TAILOR_OFFLINE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Tests cover tracking, discovery, preparation, approvals, reviewed answers, duplicate prevention, and receipts. Browser tests use disposable local forms rather than employer submissions.

Mocked model tests and offline tests do not establish that a live Gemma call succeeded. Verify local inference separately when recording a demo.

## Data and privacy

The default database is `data/lelouvre.sqlite3`. Demo mode defaults to a separate database. Runtime databases and the virtual environment are excluded from version control.

Lelouvre binds to the local loopback address by default. Files and database records are not encrypted by the app; protect them through your computer’s access controls.

Submitted archives can contain résumé attachments and application answers. Do not publish your real database, traces containing personal information, or private application materials.

For a simple backup, stop the service and copy the database to a protected location.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Hosted preview on Render

The hosted version is a **read-only preview with fictional data**. It cannot edit
profiles, run agents, prepare packets, call chat, or submit applications. All POST
requests are rejected server-side, including requests with the access token.
Local Gemma inference is demonstrated in the desktop version; Render does not run
Ollama in this configuration.

1. In Render, choose **New → Blueprint** and connect this GitHub repository.
2. Select `main` and deploy the root `render.yaml`.
3. The unauthenticated health endpoint is `/health`.
4. Read `LELOUVRE_ACCESS_TOKEN` from the service's environment settings. Open the
   service URL with `?access_token=YOUR_TOKEN`. Keep this access link private.
5. Use the generated demo database only. Free-service storage is temporary.

The deployment requires `LELOUVRE_DEMO=1` and `LELOUVRE_HOSTED=1`. Hosted mode
rejects real-workspace mode. Real candidate information belongs in your ignored
local database, never source defaults, committed files, or the hosted preview.

### Privacy maintenance

Public defaults contain no real candidate identity, GPA, or immigration answers.
Fresh real workspaces start with empty profiles and evidence banks. Existing
local databases are not overwritten by these changes. Never upload the `data/`
folder, local resume files, environment files, database backups or private traces.

The initial public commits were rewritten to remove candidate details and personal
commit email addresses. Original commit dates were retained; privacy and deployment
fixes are recorded in a separate commit. Previously downloaded copies or cached
GitHub views are outside this repository's control.
