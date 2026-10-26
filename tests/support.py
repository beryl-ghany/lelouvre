"""Explicit fictional fixtures; production defaults must stay empty."""
from lelouvre.demo import DEMO_ENTRIES


def seed_candidate(agent):
    agent.profiles.save({
        "name": "Jordan Demo", "first_name": "Jordan", "last_name": "Demo",
        "school": "Demo State University", "graduation": "May 2028", "gpa": "3.65",
    })
    for entry in DEMO_ENTRIES:
        agent.preparation.bank.upsert_entry(entry)
