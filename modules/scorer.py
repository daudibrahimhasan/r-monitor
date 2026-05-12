from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from reddit_intent_engine.modules.contact_finder import extract_urls, explicit_contact_allowed, extract_emails


DEFAULT_INTENT_POINTS = {
    "anyone got recommendations for": 15,
    "looking for": 15,
    "looking for a good": 15,
    "recommend": 15,
    "anyone know": 15,
    "need help": 15,
    "need a": 15,
    "hire": 20,
    "urgent": 20,
    "asap": 20,
    "budget": 15,
    "alternative to": 15,
    "got burned": 15,
    "worth it": 8,
    "anyone used": 8,
    "has anyone used": 8,
}

DEFAULT_SERVICE_POINTS = {
    "website": 20,
    "web design": 20,
    "web designer": 20,
    "landing page": 20,
    "wordpress": 15,
    "shopify": 15,
    "developer": 15,
    "redesign": 15,
    "conversion": 15,
}

DEFAULT_NEGATIVE_POINTS = {
    "free": -30,
    "no budget": -40,
    "student": -20,
    "homework": -40,
    "just curious": -25,
    "learning": -20,
    "not hiring": -50,
}

RESEARCH_STRONG_INTENT_PHRASES = {
    "looking for collaborator": 35,
    "looking for co-author": 40,
    "need a collaborator": 35,
    "need co-author": 40,
    "seeking collaborator": 35,
    "open to collaboration": 30,
    "want to collaborate": 30,
    "looking for research partner": 35,
    "research partner wanted": 35,
    "joint paper": 35,
    "working on a paper": 25,
    "writing a paper": 25,
    "looking for research intern": 25,
    "need research assistant": 25,
    "research help needed": 25,
    "need help with research": 25,
    "looking for help with paper": 25,
    "want to publish": 20,
    "trying to publish": 20,
    "paper submission": 20,
    "submitting to": 18,
    "conference deadline": 15,
    "need feedback on paper": 20,
    "peer review help": 20,
    "need help with experiments": 25,
    "need implementation help": 25,
    "need guidance on": 18,
    "anyone working on": 18,
    "has anyone researched": 18,
    "is there existing work on": 18,
    "looking for advice on": 15,
}

RESEARCH_WEAK_INTENT_PHRASES = {
    "help": 8,
    "question": 5,
    "advice": 8,
    "feedback": 8,
    "collaborat": 15,
    "co-author": 20,
    "research partner": 20,
    "research assistant": 18,
    "research intern": 18,
    "experiment": 10,
    "paper": 8,
    "arxiv": 8,
    "neurips": 8,
    "iclr": 8,
    "icml": 8,
    "acl": 8,
}

RESEARCH_PROMO_PHRASES = {
    "i built": -25,
    "i made": -20,
    "i created": -20,
    "just released": -25,
    "launch": -15,
    "here's what i found": -20,
    "here is what i found": -20,
    "update:": -15,
    "prize pool": -20,
    "breaking": -20,
    "recapping": -20,
    "how i made": -25,
    "my startup": -20,
    "my product": -20,
    "demo": -10,
    "showcase": -15,
}


def score_post(post: dict[str, Any], cfg: dict[str, Any]) -> int:
    if str(cfg.get("run_mode") or "").lower() == "research":
        return _score_research_post(post, cfg)

    text = f"{post.get('title','')} {post.get('body','')}".lower()
    score = 0

    created = datetime.fromisoformat(post["created_utc"])
    age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
    if age_hours <= 2:
        score += 20
    elif age_hours <= 6:
        score += 15
    elif age_hours <= 24:
        score += 8

    intent_points = DEFAULT_INTENT_POINTS
    for phrase, points in intent_points.items():
        if phrase in text:
            score += points

    # Service keywords from config get "related" points if present.
    service_points = DEFAULT_SERVICE_POINTS
    for keyword, points in service_points.items():
        if keyword in text:
            score += points

    for keyword in (cfg.get("service_keywords") or []):
        k = str(keyword).lower().strip()
        if k and k in text and k not in service_points:
            score += 10

    for competitor in (cfg.get("competitors") or []):
        c = str(competitor).lower().strip()
        if c and c in text:
            score += 15

    if "$" in text or "£" in text or "€" in text:
        score += 20

    # Contact safety (cheap checks)
    if extract_emails(text):
        score += 20
    if extract_urls(text):
        score += 15
    if explicit_contact_allowed(text):
        score += 10

    negative_points = DEFAULT_NEGATIVE_POINTS
    for phrase, points in negative_points.items():
        if phrase in text:
            score += points

    return max(0, min(int(score), 100))


def _score_research_post(post: dict[str, Any], cfg: dict[str, Any]) -> int:
    text = f"{post.get('title','')} {post.get('body','')}".lower()
    score = 0

    created = datetime.fromisoformat(post["created_utc"])
    age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
    if age_hours <= 6:
        score += 10
    elif age_hours <= 24:
        score += 6
    elif age_hours <= 72:
        score += 3

    strong_hits = 0
    for phrase, points in RESEARCH_STRONG_INTENT_PHRASES.items():
        if phrase in text:
            score += points
            strong_hits += 1

    weak_hits = 0
    for phrase, points in RESEARCH_WEAK_INTENT_PHRASES.items():
        if phrase in text:
            score += points
            weak_hits += 1

    keyword_hits = 0
    for keyword in (cfg.get("service_keywords") or []):
        k = str(keyword).lower().strip()
        if k and k in text:
            score += 4
            keyword_hits += 1
            if keyword_hits >= 6:
                break

    for phrase, points in RESEARCH_PROMO_PHRASES.items():
        if phrase in text:
            score += points

    for phrase in (cfg.get("negative_phrases") or []):
        p = str(phrase).lower().strip()
        if p and p in text:
            score -= 25

    if "?" in text:
        score += 5
    if extract_urls(text):
        score += 3
    if extract_emails(text):
        score += 5
    if explicit_contact_allowed(text):
        score += 5

    # Hard gate: only keep likely asks for help/collaboration/publishing guidance.
    has_gate = (
        strong_hits > 0
        or ("?" in text and weak_hits >= 2)
        or ("help" in text and ("paper" in text or "research" in text or "experiment" in text))
    )
    if not has_gate:
        return 0

    return max(0, min(int(score), 100))
