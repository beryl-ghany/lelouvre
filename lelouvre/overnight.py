"""Slow-and-steady digest: what happened while the scheduler ran."""
from __future__ import annotations

import json

from .gemma import GemmaClient
from .store import Problem


def build_overnight_digest(store, *, new_roles, needs_you_count, last_scout_at=None, trace_log=None):
    """Two-line summary; Gemma when available, else deterministic."""
    facts = {
        "new_roles": len(new_roles),
        "needs_you": needs_you_count,
        "last_scout": last_scout_at,
        "top_roles": [
            {"organization": r.get("organization"), "title": r.get("title"), "fit": r.get("fit_reason", "")[:120]}
            for r in new_roles[:3]
        ],
    }
    fallback = (
        f"While you were away: {facts['new_roles']} new role(s), {facts['needs_you']} waiting on you."
        if facts["new_roles"] or facts["needs_you"]
        else "Nothing new overnight. Run discover when you're ready — no rush."
    )
    client = GemmaClient()
    status = client.status()
    if not status.get("available") or not status.get("model_ready"):
        return {"summary": fallback, "source": "rules", "facts": facts}
    try:
        text, meta = client.chat(
            [
                {
                    "role": "system",
                    "content": "Write exactly two short sentences for a tired student. No hype. Mention counts. Third person ok.",
                },
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
            temperature=0,
            timeout=15,
            with_meta=True,
        )
        payload = {"summary": text.strip(), "source": "gemma", "model": client.model, "gemma_meta": meta, "facts": facts}
        if trace_log:
            trace_log.log("gemma_overnight_digest", {"gemma_meta": meta, "facts": facts})
        return payload
    except Problem:
        return {"summary": fallback, "source": "rules", "facts": facts}
