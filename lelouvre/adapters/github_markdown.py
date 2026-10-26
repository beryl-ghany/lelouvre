"""Parse community internship lists from GitHub-hosted markdown."""
from __future__ import annotations

import hashlib
import re

from ..scout import evaluate, secure_url
from ..verify import classify_apply_url

APPLY_MARKDOWN = re.compile(r"\[[^\]]*(?:apply|application)[^\]]*\]\((https://[^)]+)\)", re.I)
APPLY_HREF = re.compile(r'href="(https://[^"]+(?:greenhouse|lever|workday|smartrecruiters)[^"]*)"', re.I)
RAW_URL = re.compile(
    r"https://(?:boards|job-boards)\.greenhouse\.io/[^/\s]+/jobs/\d+|"
    r"https://jobs\.lever\.co/[^/\s]+/[a-f0-9-]+",
    re.I,
)
COMPANY_LINK = re.compile(r"\*\*\[([^\]]+)\]")


def _organization(line):
    if m := COMPANY_LINK.search(line):
        return m.group(1).strip()[:160]
    cols = [c.strip() for c in line.split("|") if c.strip()]
    if cols:
        plain = re.sub(r"\*\*|\[|\]|\([^)]+\)", "", cols[0]).strip()
        if plain:
            return plain[:160]
    return "Unknown employer"


def _title(line):
    cols = [c.strip() for c in line.split("|") if c.strip()]
    text = cols[1] if len(cols) > 1 else line
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
    text = " ".join(text.split())
    if re.search(r"\bintern", text, re.I):
        return text[:500]
    return ""


def _location(line):
    cols = [c.strip() for c in line.split("|") if c.strip()]
    if len(cols) < 3:
        return "Not listed"
    loc = re.sub(r"<[^>]+>", " ", cols[2])
    loc = " ".join(loc.split())
    return (loc or "Not listed")[:1000]


def extract_github_markdown(source, content):
    link_hosts = source.get("link_hosts", ())
    records = []
    seen_urls = set()
    for line in content.splitlines():
        if "intern" not in line.casefold():
            continue
        urls = []
        urls.extend(APPLY_MARKDOWN.findall(line))
        urls.extend(APPLY_HREF.findall(line))
        urls.extend(RAW_URL.findall(line))
        if not urls:
            continue
        organization = _organization(line)
        title = _title(line) or f"Internship — {organization}"
        location = _location(line)
        for url in urls:
            url = url.strip()
            if url in seen_urls:
                continue
            seen_urls.add(url)
            verified = classify_apply_url(url, link_hosts)
            if not verified or not secure_url(url, link_hosts):
                continue
            description = f"{title}\n{location}\n{url}\nCommunity list entry; verify posting on the employer site."
            match = evaluate(title, location, description)
            if match is None:
                continue
            match = dict(match)
            match["verification"] = verified["confidence"]
            match["apply_platform"] = verified["platform"]
            if match["target"] != "excluded":
                match.setdefault("reasons", []).append(
                    {"reason": "Verified ATS apply link from community list", "excerpt": url[:120]}
                )
            external_id = verified.get("external_job_id") or hashlib.sha256(url.encode()).hexdigest()[:24]
            records.append(
                {
                    "external_id": f"{verified['platform']}-{external_id}",
                    "organization": organization,
                    "title": title,
                    "location": location,
                    "url": verified["canonical_url"],
                    "description": description[:120000],
                    "kind": "listing",
                    "availability": "listed",
                    "evaluation": match,
                }
            )
    return records, len(content.splitlines())
