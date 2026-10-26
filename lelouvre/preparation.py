"""Prepare a reviewed, tailored application packet for a role."""
from __future__ import annotations

import json
import os

from .claim_check import filter_bullets
from .evidence_bank import EvidenceBank
from .handoff import OUTCOME_NEEDS_YOU, build_handoff
from .store import Problem
from .tailor import tailor_bullets, tailor_bullets_offline
from .tailoring import tailor_documents, verify_documents


class PreparationService:
    def __init__(self, store):
        self.bank = EvidenceBank(store)
        self.store = store

    def build_packet(self, *, organization, title, location, description, evaluation, destination):
        snapshot = self.bank.snapshot()
        posting = {
            "organization": organization,
            "title": title,
            "location": location,
            "description": description,
        }
        entries_by_id = {e["id"]: e for e in snapshot["entries"]}
        gemma_meta = {}
        offline = os.environ.get("LELOUVRE_TAILOR_OFFLINE", "").lower() in ("1", "true", "yes")
        if offline:
            raw_bullets = tailor_bullets_offline(posting, snapshot["entries"])
            source = "offline_tailor"
        else:
            try:
                from .gemma import GemmaClient
                from .tailor import TAILOR_SCHEMA, validate_tailor_payload

                client = GemmaClient()
                compact_evidence = [
                    {"id": e["id"], "title": e.get("title"), "tools": e.get("tools") or [], "summary": e.get("summary"), "results": e.get("results") or []}
                    for e in snapshot["entries"]
                ]
                prompt = (
                    "Write 4 to 6 resume bullets tailored to the job posting. "
                    "Use ONLY facts from the evidence entries. Each bullet MUST include source_id "
                    "matching an evidence entry id. Put the ID only in source_id, never in text. "
                    "Preserve the evidence wording. Do not invent tools, metrics, or employers.\n\n"
                    f"Posting:\n{json.dumps(posting, ensure_ascii=False)}\n\n"
                    f"Evidence:\n{json.dumps(compact_evidence, ensure_ascii=False)}"
                )
                raw, gemma_meta = client.chat_json(
                    [
                        {"role": "system", "content": "Return only valid JSON matching the schema."},
                        {"role": "user", "content": prompt},
                    ],
                    TAILOR_SCHEMA,
                    timeout=120,
                    with_meta=True,
                )
                raw_bullets = validate_tailor_payload(raw)
                source = "gemma_tailor"
            except Problem:
                raw_bullets = tailor_bullets_offline(posting, snapshot["entries"])
                source = "offline_tailor"
        accepted, rejected = filter_bullets(raw_bullets, entries_by_id)
        tailored = tailor_documents(
            snapshot,
            organization=organization,
            title=title,
            location=location,
            description=description,
            evaluation=evaluation,
        )
        if accepted or source == "gemma_tailor":
            tailored["resume"]["bullets"] = [
                {"id": b.get("source_id"), "text": b["text"], "evidence_id": b["source_id"], "source_entry_title": ""}
                for b in accepted
            ]
        failures = verify_documents(snapshot, tailored)
        if not snapshot["entries"]:
            failures.append({"check": "evidence", "message": "Add your own evidence entries before approving application materials."})
        for item in rejected:
            failures.append({"check": "claim", "message": item["reason"], "bullet": item["bullet"]})
        return {
            "tailored": tailored,
            "verification_failures": failures,
            "claim_rejections": rejected,
            "tailor_source": source,
            "gemma_meta": gemma_meta,
            "destination": destination,
            "approved": False,
            "source": "evidence_bank",
        }

    def approve_packet(self, packet, *, force=False):
        if packet.get("verification_failures") and not force:
            raise ValueError("Fix verification issues before approval.")
        packet = dict(packet)
        packet["approved"] = True
        inner = packet.get("tailored") or packet
        inner["resume"]["approved"] = True
        inner["cover_letter"]["approved"] = True
        packet["tailored"] = inner
        return packet

    def screening_blockers(self, field_labels):
        blockers = []
        for label in field_labels:
            match = self.bank.match_screening(label)
            if match and match["mode"] == "always_ask":
                blockers.append(
                    build_handoff(
                        "",
                        "",
                        "authorization_question",
                        extra_why=f"The form asks: {label}",
                    )
                )
                break
        return blockers


def attach_outcome_to_run(run, organization, title):
    """Map legacy run status to v0.5 outcome."""
    packet = run.get("packet") or {}
    handoff = packet.get("handoff")
    if handoff:
        return handoff.get("outcome"), handoff
    status = run.get("status")
    policy = run.get("policy") or {}
    destination = run.get("destination") or ""
    if status == "submitted":
        from .handoff import outcome_submitted

        return "submitted", outcome_submitted(organization, title, evidence=(run.get("receipt") or {}).get("evidence", ""))
    if status == "prepared" and policy.get("decision") == "approved" and packet.get("approved"):
        from .handoff import outcome_ready

        return "ready_for_you", outcome_ready(organization, title, url=destination)
    if status in ("needs_review", "receipt_unconfirmed") or policy.get("decision") == "review":
        items = policy.get("review_items") or []
        why = items[0]["reason"] if items else "Review required."
        return OUTCOME_NEEDS_YOU, build_handoff(organization, title, "review_required", url=destination, extra_why=why)
    return None, None
