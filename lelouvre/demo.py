"""Demo mode — fake profile and evidence only (LELOUVRE_DEMO=1)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_demo():
    return os.environ.get("LELOUVRE_DEMO", "").lower() in ("1", "true", "yes")


def demo_database_path():
    return Path(os.environ.get("LELOUVRE_DATABASE", str(ROOT / "data" / "lelouvre-demo.sqlite3")))


def demo_profile():
    return {
        "name": "Jordan Demo",
        "school": "Demo State University",
        "graduation": "May 2028",
        "gpa": "3.65",
        "work_authorized": "Yes (demo only)",
        "requires_sponsorship": "No (demo only)",
        "email": "jordan.demo@example.com",
    }


def demo_api_profile():
    return {
        "name": "Jordan Demo",
        "school": "Demo State University",
        "graduation": "May 2028",
        "authorization_answer": "Demo — not real immigration data",
        "sponsorship_answer": "Demo — not real immigration data",
        "cpt_approval": "Demo mode",
        "notifications": "Demo workspace only",
    }


# Stable IDs for demos, tests, and model-compare scripts.
DEMO_ENTRIES = [
    {
        "id": "demo-ev-001-inventory",
        "kind": "project",
        "title": "Campus inventory API",
        "organization": "Demo capstone",
        "tools": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "summary": "Built a REST API for campus equipment checkout with role-based access.",
        "results": ["Reduced manual tracking time by 40% for a 12-person pilot team."],
        "links": ["https://example.com/demo/inventory-api"],
        "variant_tags": ["swe"],
    },
    {
        "id": "demo-ev-002-scheduler",
        "kind": "project",
        "title": "Study group scheduler",
        "organization": "Personal",
        "tools": ["TypeScript", "React", "Node.js"],
        "summary": "Web app for scheduling study sessions with calendar sync.",
        "results": ["Supported 50 weekly active users in a beta semester."],
        "links": ["https://example.com/demo/scheduler"],
        "variant_tags": ["swe"],
    },
    {
        "id": "demo-ev-003-security",
        "kind": "project",
        "title": "Phishing lab analysis",
        "organization": "Security course",
        "tools": ["Linux", "Python", "Wireshark"],
        "summary": "Analyzed phishing kits in isolated VMs and documented IOCs.",
        "results": ["Catalogued 15 indicators shared with the class threat board."],
        "links": [],
        "variant_tags": ["security"],
    },
    {
        "id": "demo-ev-004-leadership",
        "kind": "leadership",
        "title": "ACM chapter workshops",
        "organization": "Demo State ACM",
        "tools": ["Git", "Python"],
        "summary": "Co-led weekly workshops on Git and introductory Python.",
        "results": ["Ran 8 workshops with 20+ attendees each."],
        "links": [],
        "variant_tags": ["swe", "research"],
    },
    {
        "id": "demo-ev-005-research",
        "kind": "research",
        "title": "Course recommender prototype",
        "organization": "Demo State CS lab",
        "tools": ["Python", "scikit-learn", "pandas"],
        "summary": "Prototype recommender using historical course enrollment data.",
        "results": ["Achieved 0.72 precision@5 on a held-out semester split."],
        "links": ["https://example.com/demo/recommender"],
        "variant_tags": ["research", "swe"],
    },
    {
        "id": "demo-ev-006-education",
        "kind": "education",
        "title": "B.S. Computer Science",
        "organization": "Demo State University",
        "tools": [],
        "summary": "Expected graduation May 2028; GPA 3.65.",
        "results": [],
        "links": [],
        "variant_tags": ["swe", "security", "research"],
    },
]

DEMO_SCREENING = [
    {"question_shape": "legal name", "answer": "Jordan Demo", "mode": "auto_ok"},
    {"question_shape": "school", "answer": "Demo State University", "mode": "auto_ok"},
    {"question_shape": "graduation", "answer": "May 2028", "mode": "auto_ok"},
    {"question_shape": "gpa", "answer": "3.65", "mode": "auto_ok"},
    {
        "question_shape": "sponsorship",
        "answer": "Demo answer only — always stop for human review.",
        "mode": "always_ask",
    },
    {
        "question_shape": "authorized to work",
        "answer": "Demo answer only — always stop for human review.",
        "mode": "always_ask",
    },
]
