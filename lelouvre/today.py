"""Today dashboard — three plain blocks (PRD v0.5)."""
from __future__ import annotations

import json
from datetime import date

from .scout_fit import fit_display


def _days_since(iso_date):
    if not iso_date:
        return None
    try:
        submitted = date.fromisoformat(iso_date)
        return (date.today() - submitted).days
    except ValueError:
        return None


def build_today(store, application_runs, queued_handoffs=None, overnight_digest=None):
    today_iso = date.today().isoformat()
    with store.connect() as connection:
        opportunities = [
            dict(row)
            for row in connection.execute(
                "SELECT id, type, organization, title, location, disposition, kind, evaluation, url FROM opportunities"
            )
        ]
        applications = [dict(row) for row in connection.execute("SELECT * FROM applications WHERE type='internship'")]

    run_by_opportunity = {}
    for run in application_runs:
        oid = run.get("opportunity_id")
        if oid and (oid not in run_by_opportunity or run["created_at"] > run_by_opportunity[oid]["created_at"]):
            run_by_opportunity[oid] = run

    needs_you = []
    for item in queued_handoffs or []:
        needs_you.append({**item, "kind": "handoff"})
    for run in application_runs:
        handoff = run.get("handoff") or (run.get("packet") or {}).get("handoff")
        outcome = run.get("outcome") or (handoff or {}).get("outcome")
        if outcome == "needs_you" or run.get("status") == "needs_review":
            meta = (run.get("packet") or {}).get("application") or {}
            org = meta.get("organization") or "Application"
            title = meta.get("title") or ""
            step = (handoff or {}).get("what_to_do") or "Open and finish the remaining steps."
            needs_you.append(
                {
                    "run_id": run["id"],
                    "opportunity_id": run.get("opportunity_id"),
                    "organization": org,
                    "title": title,
                    "next_step": f"{org}: {step}",
                    "url": run.get("destination") or (handoff or {}).get("url", ""),
                    "message": (handoff or {}).get("message", ""),
                }
            )
        elif outcome == "ready_for_you" or (
            run.get("status") == "prepared" and (run.get("packet") or {}).get("approved")
        ):
            meta = (run.get("packet") or {}).get("application") or {}
            org = meta.get("organization") or "Application"
            title = meta.get("title") or ""
            needs_you.append(
                {
                    "run_id": run["id"],
                    "opportunity_id": run.get("opportunity_id"),
                    "organization": org,
                    "title": title,
                    "next_step": f"{org}: open the application and submit when you're ready.",
                    "url": run.get("destination", ""),
                    "kind": "ready",
                }
            )

    for app in applications:
        if app["stage"] in ("Preparing", "Ready"):
            needs_you.append(
                {
                    "application_id": app["id"],
                    "organization": app["organization"],
                    "title": app["title"],
                    "next_step": f"{app['organization']}: get this application ready.",
                    "url": app.get("url") or "",
                    "kind": "preparing",
                }
            )

    new_roles = []
    for row in opportunities:
        if row["type"] != "internship" or row["disposition"] != "new":
            continue
        evaluation = json.loads(row["evaluation"])
        if evaluation.get("target") == "excluded":
            continue
        fit_reason, fit_source = fit_display(evaluation, row["organization"], row["title"])
        new_roles.append(
            {
                "id": row["id"],
                "organization": row["organization"],
                "title": row["title"],
                "location": row.get("location") or "",
                "fit_reason": fit_reason,
                "fit_source": fit_source,
                "blockers": evaluation.get("blockers") or [],
                "priority": evaluation.get("priority", 0),
            }
        )
    new_roles.sort(key=lambda item: (-item["priority"], item["organization"]))

    waiting = []
    for app in applications:
        if app["stage"] not in ("Applied", "Assessment", "Interview"):
            continue
        days = _days_since(app.get("submitted_date"))
        waiting.append(
            {
                "id": app["id"],
                "organization": app["organization"],
                "title": app["title"],
                "submitted_date": app.get("submitted_date"),
                "days_since": days,
                "stage": app["stage"],
                "next_follow_up": "",
            }
        )
    waiting.sort(key=lambda item: item.get("submitted_date") or "", reverse=True)

    empty_hint = "Nothing waiting on you."
    if not needs_you and not new_roles:
        empty_hint = "Nothing waiting on you. Want me to find new roles?"
    elif not needs_you:
        empty_hint = "Nothing waiting on you."

    return {
        "overnight_digest": overnight_digest,
        "needs_you": needs_you[:15],
        "new_roles": new_roles[:12],
        "waiting": waiting[:15],
        "empty_hint": empty_hint,
        # Legacy fields for gradual UI migration
        "new_matches": new_roles,
        "saved_roles": [],
        "packets_review": [],
        "tasks": [],
        "interviews": [],
        "primary_action": {"label": "Find new roles", "route": "today", "action": "internship-agent-run"},
    }
