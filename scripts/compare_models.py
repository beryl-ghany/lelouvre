#!/usr/bin/env python3
"""Compare two Ollama models on tailor + claim_check + form fixture (steps 2–5)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LELOUVRE_DEMO", "1")

from lelouvre.claim_check import filter_bullets
from lelouvre.demo import DEMO_ENTRIES
from lelouvre.form_reader import run_fixture_form
from lelouvre.local_llm import OllamaProvider
from lelouvre.tailor import tailor_bullets, tailor_bullets_offline

POSTING = {
    "organization": "Demo Corp",
    "title": "Software Engineering Intern",
    "location": "New York, NY",
    "description": "Python FastAPI PostgreSQL React internship summer 2027 backend APIs.",
}


def run_model(model_name):
    provider = OllamaProvider(model=model_name)
    t0 = time.perf_counter()
    try:
        bullets = tailor_bullets(POSTING, DEMO_ENTRIES, llm=provider)
        tailor_mode = "ollama"
    except Exception:
        bullets = tailor_bullets_offline(POSTING, DEMO_ENTRIES)
        tailor_mode = "offline"
    elapsed = time.perf_counter() - t0
    entries = {e["id"]: e for e in DEMO_ENTRIES}
    inflated = bullets + [{"text": "Built Kubernetes cluster serving 10M requests.", "source_id": "demo-ev-001-inventory"}]
    _, rejected = filter_bullets(inflated, entries)
    form = run_fixture_form()
    stopped_ok = form.get("outcome") == "needs_you" and form.get("handoff", {}).get("reason_code") == "authorization_question"
    return {
        "model": model_name,
        "seconds": round(elapsed, 2),
        "tailor_mode": tailor_mode,
        "bullets": len(bullets),
        "rejected": len(rejected),
        "form_stop_ok": stopped_ok,
    }


def main():
    models = [
        os.environ.get("LELOUVRE_OLLAMA_MODEL", "gemma4:e2b"),
        os.environ.get("LELOUVRE_COMPARE_MODEL", os.environ.get("LELOUVRE_OLLAMA_MODEL", "gemma4:e2b")),
    ]
    if models[0] == models[1]:
        models[1] = os.environ.get("LELOUVRE_COMPARE_MODEL", "llama3.2")
    rows = [run_model(m) for m in models[:2]]
    headers = ("Model", "Time (s)", "Tailor", "Bullets", "Rejected", "Stopped at sponsor")
    print("\t".join(headers))
    for row in rows:
        print(
            f"{row['model']}\t{row['seconds']}\t{row['tailor_mode']}\t{row['bullets']}\t"
            f"{row['rejected']}\t{row['form_stop_ok']}"
        )


if __name__ == "__main__":
    main()
