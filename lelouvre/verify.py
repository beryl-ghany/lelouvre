"""Deterministic ATS detection and apply-url verification (no model calls)."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

GREENHOUSE = re.compile(
    r"^https://(?:(?:boards|job-boards)\.greenhouse\.io|boards\.eu\.greenhouse\.io)/(?P<board>[^/]+)/jobs/(?P<job_id>\d+)(?:\?.*)?$",
    re.I,
)
LEVER = re.compile(r"^https://jobs\.lever\.co/(?P<board>[^/]+)/(?P<job_id>[a-f0-9-]+)(?:\?.*)?$", re.I)
WORKDAY = re.compile(r"^https://[^/]+\.(?:myworkdayjobs\.com|wd\d+\.myworkdayjobs\.com)/", re.I)

APPLY_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "jobs.lever.co",
        "apply.workable.com",
        "jobs.smartrecruiters.com",
    }
)


def _secure(url):
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        )
    except (ValueError, TypeError):
        return False


def is_allowed_apply_host(hostname, extra=()):
    if not hostname:
        return False
    host = hostname.casefold()
    if host in APPLY_HOSTS or host in {h.casefold() for h in extra}:
        return True
    if host.endswith(".myworkdayjobs.com"):
        return True
    return False


def classify_apply_url(url, extra_hosts=()):
    if not _secure(url):
        return None
    parsed = urlsplit(url)
    if not is_allowed_apply_host(parsed.hostname, extra_hosts):
        return None
    if m := GREENHOUSE.match(url):
        return {
            "platform": "greenhouse",
            "canonical_url": url.split("?", 1)[0],
            "board": m.group("board"),
            "external_job_id": m.group("job_id"),
            "confidence": "verified_ats",
        }
    if m := LEVER.match(url):
        return {
            "platform": "lever",
            "canonical_url": url.split("?", 1)[0],
            "board": m.group("board"),
            "external_job_id": m.group("job_id"),
            "confidence": "verified_ats",
        }
    if WORKDAY.match(url):
        return {
            "platform": "workday",
            "canonical_url": url.split("?", 1)[0],
            "board": parsed.hostname or "",
            "external_job_id": parsed.path.rstrip("/").rsplit("/", 1)[-1],
            "confidence": "verified_ats",
        }
    return {
        "platform": "other_ats",
        "canonical_url": url.split("?", 1)[0],
        "board": parsed.hostname or "",
        "external_job_id": "",
        "confidence": "verified_ats",
    }


def extract_urls(text):
    if not text:
        return []
    found = []
    for match in re.finditer(r"https://[^\s\])\"'<>]+", str(text)):
        url = match.group(0).rstrip(".,)")
        if _secure(url):
            found.append(url)
    return found


def best_apply_url(text, preferred=None, extra_hosts=()):
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(extract_urls(text))
    seen = set()
    ranked = []
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        info = classify_apply_url(url, extra_hosts)
        if info:
            ranked.append((0 if info["platform"] == "greenhouse" else 1, url, info))
    if not ranked:
        return None, None
    ranked.sort(key=lambda item: item[0])
    _, url, info = ranked[0]
    return url, info
