"""Parse public Reddit listing JSON into internship leads."""
from __future__ import annotations

import json
import re

from ..scout import evaluate
from ..verify import best_apply_url

INTERN_HINT = re.compile(r"\bintern(?:ship)?\b", re.I)


def extract_reddit_json(source, content):
    link_hosts = source.get("link_hosts", ())
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("Reddit source did not return JSON") from error
    children = payload.get("data", {}).get("children")
    if not isinstance(children, list):
        raise ValueError("Reddit JSON missing listing children")
    records = []
    for child in children:
        if not isinstance(child, dict) or child.get("kind") != "t3":
            continue
        data = child.get("data")
        if not isinstance(data, dict):
            continue
        post_id = data.get("id")
        title = str(data.get("title", ""))[:500]
        if not post_id or not INTERN_HINT.search(title):
            continue
        selftext = str(data.get("selftext", ""))[:120000]
        link = str(data.get("url", ""))
        body = f"{title}\n{selftext}"
        apply_url, verified = best_apply_url(body, preferred=None if data.get("is_self") else link, extra_hosts=link_hosts)
        location = "Not listed"
        if m := re.search(r"(?:location|based in)[:\s]+([^\n|]+)", selftext, re.I):
            location = m.group(1).strip()[:1000]
        description = body[:120000]
        match = evaluate(title, location, description)
        if match is None:
            continue
        match = dict(match)
        kind = "listing" if verified else "lead"
        match["verification"] = verified["confidence"] if verified else "unverified_lead"
        if not verified:
            match.setdefault("blockers", []).append(
                "Community post: resolve an official employer apply URL before any submission."
            )
            if match["target"] != "excluded":
                match["target"] = "needs_review"
        else:
            match["apply_platform"] = verified["platform"]
            match.setdefault("reasons", []).append(
                {"reason": "Apply URL detected in community post", "excerpt": apply_url[:120]}
            )
        records.append(
            {
                "external_id": post_id,
                "title": title,
                "location": location,
                "url": apply_url or f"https://www.reddit.com{data.get('permalink', '')}",
                "description": description,
                "kind": kind,
                "availability": "listed",
                "evaluation": match,
            }
        )
    return records, len(children)
