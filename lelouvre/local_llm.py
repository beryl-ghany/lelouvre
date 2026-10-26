"""Listing analysis via local Gemma (Ollama). No paid API is required."""
from __future__ import annotations

import json
import re

from .gemma import GemmaClient, resolve_gemma_model
from .store import Problem


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "role_category": {"type": "string", "enum": ["software_engineering", "cybersecurity", "cloud_security", "undergraduate_research", "other"]},
        "season": {"type": "string", "enum": ["summer_2027", "other", "unknown"]},
        "location_status": {"type": "string", "enum": ["us_outside_south_carolina", "south_carolina", "outside_us", "unknown"]},
        "eligibility": {"type": "string", "enum": ["likely", "needs_review", "unlikely"]},
        "summary": {"type": "string"},
        "requirements": {"type": "array", "items": {"type": "string"}},
        "review_flags": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["role_category", "season", "location_status", "eligibility", "summary", "requirements", "review_flags", "evidence"],
    "additionalProperties": False,
}


class OllamaProvider:
    """Backward-compatible name; uses GemmaClient under the hood."""

    def __init__(self, model=None, endpoint=None, transport=None, client=None):
        if client is not None:
            self._gemma = client
        elif transport is not None:
            def adapter(url, payload, timeout=120):
                return transport(payload)

            self._gemma = GemmaClient(model=model or resolve_gemma_model(), transport=adapter)
        else:
            base = None
            if endpoint:
                base = endpoint.rstrip("/").removesuffix("/api/chat")
            self._gemma = GemmaClient(model=model, base_url=base)
        self.model = self._gemma.model
        self.client = self._gemma

    def analyze(self, listing):
        prompt = (
            "Analyze this opportunity only from the supplied text. Do not invent facts. "
            "Discovery is based on role category, season, and location; resume skill overlap must not gate or rank it. "
            "Flag uncertain eligibility, citizenship/clearance restrictions, essays, assessments, sensitive disclosures, and commitments.\n\n"
            + json.dumps(listing, ensure_ascii=False)
        )
        analysis = self._gemma.chat_json(
            [
                {"role": "system", "content": "Return only schema-valid evidence-grounded analysis."},
                {"role": "user", "content": prompt},
            ],
            ANALYSIS_SCHEMA,
        )
        missing = [key for key in ANALYSIS_SCHEMA["required"] if key not in analysis]
        if missing:
            raise Problem("The local model omitted required analysis fields.", 502, "local_model_invalid", fields=missing)
        self._reconcile(analysis, listing)
        analysis["provider"] = "gemma"
        analysis["model"] = self.model
        return analysis

    @staticmethod
    def _reconcile(analysis, listing):
        """Core discovery facts are rule-verified; the model may explain but not invent them."""
        title = str(listing.get("title", "")); location = str(listing.get("location", ""))
        description = str(listing.get("description", "")); combined = title + " " + description
        category = ("cloud_security" if re.search(r"cloud.{0,20}security|security.{0,20}cloud", title, re.I)
                    else "cybersecurity" if re.search(r"cyber|security", title, re.I)
                    else "undergraduate_research" if re.search(r"research", title, re.I)
                    else "software_engineering" if re.search(r"software|developer|backend|frontend|full.?stack|platform|infrastructure", title, re.I)
                    else "other")
        season = "summer_2027" if re.search(r"summer\s*(?:of\s*)?2027|2027\s*summer", combined, re.I) else "unknown"
        if re.search(r"south carolina|,\s*SC\b|orangeburg", location, re.I): place = "south_carolina"
        elif re.search(r"seattle|new york|boston|san francisco|san jose|los angeles|austin|denver|washington,?\s*dc|chicago|,\s*(?:CA|NY|MA|WA|TX|CO|VA|NC|GA|PA|NJ|FL|IL)\b", location, re.I): place = "us_outside_south_carolina"
        elif re.search(r"france|canada|united kingdom|germany|india|singapore|australia", location, re.I): place = "outside_us"
        else: place = "unknown"
        for key, verified in (("role_category", category), ("season", season), ("location_status", place)):
            if analysis.get(key) != verified:
                analysis.setdefault("review_flags", []).append(f"Model {key} corrected from {analysis.get(key)} to {verified} by deterministic evidence check.")
                analysis[key] = verified

