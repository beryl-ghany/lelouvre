"""Deterministic submission readiness — code decides; model output is advisory only."""
from __future__ import annotations

import re

HIGH_RISK_FLAG = re.compile(
    r"essay|cover.?letter|assessment|clearance|citizenship|salary|demographic|"
    r"disability|veteran|gender|race|ethnicity|sensitive|commitment|unlikely",
    re.I,
)


def analysis_advisories(analysis):
    """Return human-readable reasons the LLM analysis suggests manual review."""
    if not analysis or analysis.get("provider") == "none":
        return []
    notes = []
    if analysis.get("eligibility") == "unlikely":
        notes.append("Local analysis marked eligibility as unlikely.")
    if analysis.get("eligibility") == "needs_review":
        notes.append("Local analysis flagged eligibility for review.")
    for flag in analysis.get("review_flags") or []:
        if HIGH_RISK_FLAG.search(str(flag)):
            notes.append(f"Analysis flag: {flag}")
    return notes


def auto_execute_blockers(packet, evaluation):
    """Block unattended execute unless discovery rules and analysis are clean."""
    blockers = []
    if evaluation.get("verification") not in (None, "verified_ats"):
        if evaluation.get("verification") == "unverified_lead":
            blockers.append("Apply URL is not verified.")
    if evaluation.get("target") != "potential_match":
        blockers.append("Discovery target is not a confirmed potential match.")
    if evaluation.get("season") != "confirmed":
        blockers.append("Summer 2027 season is not confirmed by deterministic rules.")
    blockers.extend(analysis_advisories((packet or {}).get("analysis")))
    return blockers
