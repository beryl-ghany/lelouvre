"""Tailor resume bullets from a posting + evidence bank via local Gemma."""
from __future__ import annotations

import json
import re

from .gemma import GemmaClient
from .store import Problem

TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {
            "type": "array",
            "minItems": 4,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["text", "source_id"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["bullets"],
    "additionalProperties": False,
}


def validate_tailor_payload(data):
    if not isinstance(data, dict):
        raise Problem("Tailor output must be a JSON object.", 502, "tailor_invalid")
    bullets = data.get("bullets")
    if not isinstance(bullets, list) or not 4 <= len(bullets) <= 6:
        raise Problem("Tailor output must include 4 to 6 bullets.", 502, "tailor_invalid")
    valid_ids = None
    for item in bullets:
        if not isinstance(item, dict):
            raise Problem("Each bullet must be an object.", 502, "tailor_invalid")
        text = item.get("text")
        source_id = item.get("source_id")
        if not isinstance(text, str) or not text.strip():
            raise Problem("Each bullet needs non-empty text.", 502, "tailor_invalid")
        if not isinstance(source_id, str) or not source_id.strip():
            raise Problem("Each bullet needs source_id.", 502, "tailor_invalid")
        # Some models repeat their citation in prose. Remove only the exact
        # trailing metadata citation; keep all factual text for claim checking.
        item["text"] = re.sub(r"\s*\(source_id:\s*" + re.escape(source_id) + r"\)\s*$", "", text).strip()
    return bullets


def tailor_bullets(posting, evidence_entries, *, llm=None, client=None):
    """Return list of {text, source_id} from Gemma. Raises Problem if model unavailable."""
    gemma = client or (llm.client if llm and hasattr(llm, "client") else None) or GemmaClient()
    compact_evidence = [
        {
            "id": e["id"],
            "title": e.get("title"),
            "tools": e.get("tools") or [],
            "summary": e.get("summary"),
            "results": e.get("results") or [],
        }
        for e in evidence_entries
    ]
    prompt = (
        "Write 4 to 6 resume bullets tailored to the job posting. "
        "Use ONLY facts from the evidence entries. Each bullet MUST include source_id "
        "matching an evidence entry id. Put the ID only in source_id, never in text. "
        "Preserve the evidence wording. Do not invent tools, metrics, or employers.\n\n"
        f"Posting:\n{json.dumps(posting, ensure_ascii=False)}\n\n"
        f"Evidence:\n{json.dumps(compact_evidence, ensure_ascii=False)}"
    )
    try:
        raw = gemma.chat_json(
            [
                {"role": "system", "content": "Return only valid JSON matching the schema."},
                {"role": "user", "content": prompt},
            ],
            TAILOR_SCHEMA,
            timeout=120,
        )
    except Problem:
        raise
    except Exception as error:
        raise Problem("Tailor model call failed.", 503, "tailor_unavailable") from error
    return validate_tailor_payload(raw)


def tailor_bullets_offline(posting, evidence_entries):
    """Deterministic fallback when Ollama is off — still returns source_id links."""
    description = (posting.get("description") or "").casefold()
    chosen = []
    for entry in evidence_entries:
        score = sum(1 for t in (entry.get("tools") or []) if t.casefold() in description)
        if score or entry.get("kind") == "project":
            chosen.append((score, entry))
    chosen.sort(key=lambda x: -x[0])
    bullets = []
    for _, entry in chosen[:6]:
        result = (entry.get("results") or [entry.get("summary")])[0]
        bullets.append({"text": f"{entry['title']}: {result}", "source_id": entry["id"]})
    while len(bullets) < 4 and evidence_entries:
        entry = evidence_entries[len(bullets) % len(evidence_entries)]
        result = (entry.get("results") or [entry.get("summary")])[0]
        bullets.append({"text": f"{entry['title']}: {result}", "source_id": entry["id"]})
    return bullets[:6]
