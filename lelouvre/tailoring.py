"""Tailored resume and cover letter with evidence links and verification (PRD v0.5)."""
from __future__ import annotations

import re
from uuid import uuid4

from .evidence_bank import pick_variant

GENERIC_OPENERS = re.compile(r"^I am (?:excited|thrilled|passionate)|^Dear Hiring Manager", re.I)


def one_line_fit(evaluation, organization, title):
    skills = evaluation.get("matched_skills") or []
    if skills:
        names = ", ".join(s["skill"] for s in skills[:3])
        return f"{organization}, {title}. Matches your {names} experience."
    reasons = evaluation.get("reasons") or []
    if reasons:
        return f"{organization}, {title}. {reasons[0].get('reason', 'Fits your target track')}."
    track = evaluation.get("track") or "internship"
    return f"{organization}, {title}. Fits your {track} track for Summer 2027."


def _score_entry(entry, description_cf, variant):
    tags = entry.get("variant_tags") or []
    if variant not in tags and "swe" not in tags:
        return 0
    score = 0
    for tool in entry.get("tools") or []:
        if tool.casefold() in description_cf:
            score += 3
    if entry.get("title", "").casefold() in description_cf:
        score += 2
    for word in re.findall(r"[a-z]{4,}", entry.get("summary", "").casefold()):
        if word in description_cf:
            score += 1
    return score


def tailor_documents(bank_snapshot, *, organization, title, location, description, evaluation=None):
    evaluation = evaluation or {}
    description_cf = description.casefold()
    variant = pick_variant(title, description)
    entries = bank_snapshot["entries"]
    ranked = sorted(
        ((e, _score_entry(e, description_cf, variant)) for e in entries),
        key=lambda item: -item[1],
    )
    selected = [e for e, score in ranked if score > 0][:5]
    if not selected:
        selected = entries[:4]

    master = bank_snapshot["master_resume"]
    resume_bullets = []
    used_evidence = set()
    for entry in selected:
        result = (entry.get("results") or [entry.get("summary")])[0]
        bullet_text = f"{entry['title']}: {result}"
        resume_bullets.append(
            {
                "id": uuid4().hex,
                "text": bullet_text,
                "evidence_id": entry["id"],
                "source_entry_title": entry["title"],
            }
        )
        used_evidence.add(entry["id"])

    resume = {
        "variant": variant,
        "version": (master.get("version") or 0) + 1,
        "name": master.get("name", "Jordan Demo"),
        "headline": master.get("headline", ""),
        "organization_target": organization,
        "role_target": title,
        "location": location,
        "bullets": resume_bullets,
        "approved": False,
    }

    product_hint = organization
    if re.search(r"cloudflare|cdn|edge", description_cf):
        product_hint = "edge and developer platform work"
    elif re.search(r"datadog|observability|monitoring", description_cf):
        product_hint = "observability and platform reliability"
    lead_result = resume_bullets[0]["text"] if resume_bullets else "recent software and security projects"
    cover_letter = {
        "paragraphs": [
            f"I am applying for the {title} role at {organization}. "
            f"Your focus on {product_hint} aligns with work I've done building {lead_result.split(':')[0]}.",
            f"In that project, {lead_result.split(':', 1)[-1].strip()} "
            f"I would welcome contributing similar hands-on engineering on your team this summer.",
        ],
        "approved": False,
        "concrete_detail": product_hint,
        "concrete_result": lead_result,
    }

    matched_skills = {s["skill"].casefold() for s in (evaluation.get("matched_skills") or [])}
    listed_skills = {t.casefold() for e in selected for t in (e.get("tools") or [])}
    highlight_skills = sorted(matched_skills - listed_skills)
    gaps = [g.get("skill") for g in (evaluation.get("gaps") or [])]

    diff = []
    master_texts = {b.get("text") for b in master.get("bullets") or []}
    for bullet in resume_bullets:
        if bullet["text"] not in master_texts:
            diff.append({"kind": "add", "text": bullet["text"], "evidence_id": bullet["evidence_id"]})
    for bullet in master.get("bullets") or []:
        if bullet.get("text") not in {b["text"] for b in resume_bullets}:
            diff.append({"kind": "remove", "text": bullet["text"], "evidence_id": bullet.get("evidence_id")})

    return {
        "resume": resume,
        "cover_letter": cover_letter,
        "diff": diff,
        "highlight_skills": highlight_skills,
        "gaps": gaps,
        "variant": variant,
    }


def verify_documents(bank_snapshot, tailored):
    failures = []
    entries_by_id = {e["id"]: e for e in bank_snapshot["entries"]}
    banned = bank_snapshot.get("voice", {}).get("banned_phrases") or []

    for bullet in tailored["resume"]["bullets"]:
        entry = entries_by_id.get(bullet["evidence_id"])
        if not entry:
            failures.append({"check": "claim", "message": f"No evidence entry for bullet: {bullet['text'][:80]}"})
            continue
        allowed = " ".join(
            [entry["title"], entry["summary"], entry["organization"], bullet["text"]]
            + (entry.get("tools") or [])
            + (entry.get("results") or [])
        ).casefold()
        bullet_cf = bullet["text"].casefold()
        if not any(part in allowed for part in bullet_cf.split(": ", 1)[-1].split() if len(part) > 3):
            failures.append(
                {
                    "check": "claim",
                    "message": f"Bullet may not trace to evidence: {bullet['text'][:100]}",
                }
            )

    letter = " ".join(tailored["cover_letter"]["paragraphs"])
    if GENERIC_OPENERS.search(letter):
        failures.append({"check": "quality", "message": "Cover letter opener is too generic."})
    for phrase in banned:
        if phrase.casefold() in letter.casefold():
            failures.append({"check": "quality", "message": f"Banned phrase in cover letter: {phrase}"})
    if not tailored["cover_letter"].get("concrete_detail"):
        failures.append({"check": "quality", "message": "Cover letter lacks a concrete team or product detail."})

    if len(tailored["resume"]["bullets"]) > 8:
        failures.append({"check": "quality", "message": "Tailored resume exceeds one-page bullet budget."})

    return failures

