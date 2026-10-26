"""Plain-language application outcomes and handoff messages (PRD v0.5)."""
from __future__ import annotations

OUTCOME_SUBMITTED = "submitted"
OUTCOME_READY = "ready_for_you"
OUTCOME_NEEDS_YOU = "needs_you"

REASON_COPY = {
    "authorization_question": (
        "The form asks about work authorization or sponsorship in a way I haven't approved.",
        "Answer that question yourself, then submit. Everything else is filled in.",
    ),
    "essay_required": (
        "This application needs a written answer I can only draft, not send.",
        "Review my draft, then submit.",
    ),
    "assessment_required": (
        "An online assessment is required.",
        "Complete the assessment.",
    ),
    "captcha": (
        "The site showed a CAPTCHA.",
        "Solve it and submit.",
    ),
    "login_or_code": (
        "The site needs you to sign in or enter an emailed code.",
        "Sign in, then continue.",
    ),
    "upload_failed": (
        "I couldn't upload your resume.",
        "Upload the PDF I saved.",
    ),
    "posting_closed": (
        "The posting is closed or moved.",
        "Nothing — I've marked it closed.",
    ),
    "unfamiliar_form": (
        "The page doesn't look like what I expected and I wasn't confident.",
        "Apply manually with the answers I prepared.",
    ),
    "low_confidence_field": (
        "I wasn't sure about a field and didn't guess.",
        "Fill in the flagged field.",
    ),
    "season_or_location": (
        "Season or location doesn't match your rules.",
        "Decide whether to apply anyway.",
    ),
    "review_required": (
        "Something in this application needs your review before I can finish.",
        "Open the application and complete the steps listed below.",
    ),
    "host_not_enabled": (
        "Automatic submit isn't turned on for this employer site yet.",
        "Open the link and submit yourself using the documents I prepared.",
    ),
    "packet_not_approved": (
        "Your tailored resume and cover letter aren't approved yet.",
        "Review the changes, approve them, then try again.",
    ),
}


def build_handoff(organization, title, reason_code, *, url="", extra_why="", actions=None):
    why, default_action = REASON_COPY.get(
        reason_code,
        ("I couldn't finish this application automatically.", "Finish the remaining steps yourself."),
    )
    if extra_why:
        why = extra_why
    action = (actions or [default_action])[0]
    return {
        "outcome": OUTCOME_NEEDS_YOU,
        "reason_code": reason_code,
        "headline": f"Couldn't finish: {organization}, {title}",
        "why": why,
        "what_to_do": action,
        "url": url or "",
        "message": (
            f"Couldn't finish: {organization}, {title}\n"
            f"Why: {why}\n"
            f"What to do: {action}"
        ),
    }


def outcome_ready(organization, title, *, url=""):
    return {
        "outcome": OUTCOME_READY,
        "headline": f"Ready for you: {organization}, {title}",
        "why": "Your application is complete. Press submit when you're ready.",
        "what_to_do": "Open the application and submit.",
        "url": url or "",
        "message": f"Ready for you: {organization}, {title}. Open the link and submit.",
    }


def outcome_submitted(organization, title, *, evidence=""):
    return {
        "outcome": OUTCOME_SUBMITTED,
        "headline": f"Submitted: {organization}, {title}",
        "why": evidence or "Confirmation received.",
        "what_to_do": "",
        "url": "",
        "message": f"Submitted: {organization}, {title}. {evidence or 'Saved a copy of what was sent.'}",
    }
