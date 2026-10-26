"""One-line Gemma fit blurbs for newly discovered roles (cached on evaluation JSON)."""
from __future__ import annotations

import json
import os

from .gemma import GemmaClient
from .store import Problem
from .tailoring import one_line_fit


def _offline():
    return os.environ.get("LELOUVRE_TAILOR_OFFLINE", "").lower() in ("1", "true", "yes")


def _facts_from_row(row):
    evaluation = json.loads(row["evaluation"]) if isinstance(row["evaluation"], str) else row["evaluation"]
    description = (row.get("description") or "")[:800]
    return {
        "organization": row.get("organization"),
        "title": row.get("title"),
        "location": row.get("location") or "",
        "target": evaluation.get("target"),
        "track": evaluation.get("track"),
        "matched_skills": [m.get("skill") for m in (evaluation.get("matched_skills") or [])[:5]],
        "reasons": [r.get("reason") for r in (evaluation.get("reasons") or [])[:3]],
        "blockers": evaluation.get("blockers") or [],
        "description_excerpt": description,
        "rules_fit": one_line_fit(evaluation, row.get("organization"), row.get("title")),
    }


def gemma_fit_for_opportunity(row, *, client=None, trace_log=None):
    """Return updated evaluation dict with gemma_fit; does not write DB."""
    evaluation = json.loads(row["evaluation"]) if isinstance(row["evaluation"], str) else dict(row["evaluation"])
    existing = evaluation.get("gemma_fit") or {}
    if existing.get("blurb") and existing.get("source") == "gemma":
        return evaluation

    facts = _facts_from_row(row)
    fallback = {"blurb": facts["rules_fit"], "source": "rules", "meta": None}

    if _offline():
        evaluation["gemma_fit"] = fallback
        return evaluation

    client = client or GemmaClient()
    status = client.status()
    if not status.get("available") or not status.get("model_ready"):
        evaluation["gemma_fit"] = fallback
        return evaluation

    try:
        content, meta = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Write one honest sentence for a student hunting Summer 2027 internships. "
                        "Use only the JSON facts. No hype. Mention a skill match or blocker if present."
                    ),
                },
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
            temperature=0,
            timeout=12,
            with_meta=True,
        )
        blurb = content.strip().split("\n")[0][:240]
        evaluation["gemma_fit"] = {"blurb": blurb, "source": "gemma", "meta": meta}
        if trace_log:
            trace_log.log(
                "gemma_scout_fit",
                {
                    "opportunity_id": row.get("id"),
                    "organization": row.get("organization"),
                    "title": row.get("title"),
                    "gemma_meta": meta,
                },
            )
    except Problem:
        evaluation["gemma_fit"] = fallback
    return evaluation


def enrich_new_discovery_fits(store, *, limit=5, trace_log=None):
    """Fill gemma_fit for new internship listings (bounded Gemma calls)."""
    if limit <= 0:
        return {"enriched": 0}
    with store.connect() as connection:
        rows = connection.execute(
            """SELECT id, organization, title, location, description, evaluation FROM opportunities
               WHERE disposition='new' AND type='internship'
               ORDER BY last_seen DESC LIMIT ?""",
            (max(limit * 3, limit),),
        ).fetchall()
    enriched = 0
    client = None if _offline() else GemmaClient()
    for row in rows:
        if enriched >= limit:
            break
        evaluation = json.loads(row["evaluation"])
        gf = evaluation.get("gemma_fit") or {}
        if gf.get("source") == "gemma" and gf.get("blurb"):
            continue
        updated = gemma_fit_for_opportunity(dict(row), client=client, trace_log=trace_log)
        if updated.get("gemma_fit") == gf:
            continue
        with store.connect() as connection:
            connection.execute(
                "UPDATE opportunities SET evaluation=? WHERE id=?",
                (json.dumps(updated, ensure_ascii=False), row["id"]),
            )
        enriched += 1
    return {"enriched": enriched}


def fit_display(evaluation, organization, title):
    gf = (evaluation or {}).get("gemma_fit") or {}
    if gf.get("blurb"):
        return gf["blurb"], gf.get("source", "rules")
    return one_line_fit(evaluation or {}, organization, title), "rules"
