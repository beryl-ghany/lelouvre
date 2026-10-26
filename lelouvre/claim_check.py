"""Deterministic claim validation for tailored bullets (no model)."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("lelouvre.claim_check")

NUMBER = re.compile(r"\b\d+(?:\.\d+)?%?\b")
WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9+#.-]{2,}\b")


def entry_corpus(entry):
    parts = [
        entry.get("title", ""),
        entry.get("summary", ""),
        entry.get("organization", ""),
        " ".join(entry.get("tools") or []),
        " ".join(entry.get("results") or []),
    ]
    return " ".join(parts).casefold()


def check_bullet(bullet, entries_by_id):
    """Return None if OK, else human-readable rejection reason."""
    source_id = bullet.get("source_id")
    text = bullet.get("text") or ""
    if source_id not in entries_by_id:
        return f"source_id '{source_id}' does not exist in the evidence bank"
    corpus = entry_corpus(entries_by_id[source_id])
    text_cf = text.casefold()

    for match in NUMBER.finditer(text):
        token = match.group(0)
        if token.casefold() not in corpus:
            return f"number '{token}' in bullet is not supported by source entry {source_id}"

    for match in WORD.finditer(text):
        token = match.group(0)
        low = token.casefold()
        if low in {"and", "the", "for", "with", "using", "built", "developed", "demo", "campus", "api"}:
            continue
        if low not in corpus and not any(low in tool.casefold() for tool in entries_by_id[source_id].get("tools") or []):
            if len(token) >= 4 and token[0].isupper():
                return f"tool or term '{token}' is not in source entry {source_id}"
    return None


def filter_bullets(bullets, entries_by_id):
    """Split bullets into accepted and rejected; log rejections."""
    accepted, rejected = [], []
    for bullet in bullets:
        reason = check_bullet(bullet, entries_by_id)
        if reason:
            logger.info("Rejected bullet: %s — %s", bullet.get("text", "")[:80], reason)
            rejected.append({"bullet": bullet, "reason": reason})
        else:
            accepted.append(bullet)
    return accepted, rejected
