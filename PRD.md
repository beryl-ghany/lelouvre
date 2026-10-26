# Lelouvre PRD v0.5

Oct 25, 2026 · @Beryl

v0.5 makes one thing excellent: for a suitable Summer 2027 internship, Lelouvre finds it, tailors a truthful resume and cover letter, lets you review the changes, then either submits or tells you in plain words why you need to finish it yourself, and saves exactly what was sent.

Implementation status: **core loop shipped on local stack (0.5.0)** — evidence bank, tailoring, diff review, three-outcome handoffs, Today three-block UI, submission archive. Cloud Postgres, open browser agent, and notifications are **0.6+** per roadmap below.

See the full product specification in the user-authored PRD (sections 1–16). Build order completed in code:

1. Evidence bank (`lelouvre/evidence_bank.py`, `/api/evidence`)
2. Tailoring + claim check (`lelouvre/tailoring.py`)
3. Diff review + approve (`POST /api/application-runs/{id}/approve`)
4. Handoff outcomes (`lelouvre/handoff.py`)
5. Today three blocks (`lelouvre/today.py`, `web/app.js`)
6. Archive (`application_archive` table, `/api/applications/{id}/archive`)
