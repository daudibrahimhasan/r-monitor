from __future__ import annotations

from pathlib import Path
from typing import Any


def _load_template(base_dir: Path, rel_path: str) -> str | None:
    p = (base_dir / rel_path).resolve()
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def generate_outreach(
    post: dict[str, Any],
    cfg: dict[str, Any],
    *,
    contact: dict[str, Any] | None,
) -> dict[str, str]:
    base_dir = Path(__file__).resolve().parents[1]
    offer = cfg.get("offer", {}) or {}

    problem = extract_problem(post, cfg)
    subject = f"saw your post about {problem}"

    template = _load_template(base_dir, "templates/first_email.txt")
    if template:
        body = template.format(
            subreddit=post.get("subreddit", ""),
            problem=problem,
            sender_name=offer.get("sender_name", "Your Name"),
            company_name=offer.get("company_name", "Your Company"),
            one_liner=offer.get("one_liner", ""),
            proof=offer.get("proof", ""),
            cta=offer.get("cta", "Worth a quick 15-minute call?"),
            source_url=post.get("url", ""),
        )
    else:
        body = (
            "Hey,\n\n"
            f"Saw your Reddit post in r/{post.get('subreddit','')} about {problem}.\n\n"
            "Based on what you wrote, it sounds like you need someone who can help quickly without making the process complicated.\n\n"
            f"{offer.get('one_liner','')}\n\n"
            f"{offer.get('cta','Worth a quick 15-minute call?')}\n\n"
            f"Best,\n{offer.get('sender_name','Your Name')}\n\n"
            "P.S. If this is not relevant, reply “no” and I will not follow up.\n"
        )

    # If we only have a Reddit contact path, draft a reply/DM template for review.
    if contact and contact.get("type") == "reddit_review":
        reddit_template = _load_template(base_dir, "templates/reddit_reply.txt")
        if reddit_template:
            body = reddit_template.format(
                subreddit=post.get("subreddit", ""),
                problem=problem,
                sender_name=offer.get("sender_name", "Your Name"),
                company_name=offer.get("company_name", "Your Company"),
                one_liner=offer.get("one_liner", ""),
                proof=offer.get("proof", ""),
                cta=offer.get("cta", "Want me to share 2–3 quick suggestions?"),
                source_url=post.get("url", ""),
            )

    return {"subject": subject, "body": body}


def extract_problem(post: dict[str, Any], cfg: dict[str, Any]) -> str:
    text = f"{post.get('title','')} {post.get('body','')}".lower()

    # Prefer config-driven keyword match, longest-first.
    keywords = sorted({str(k).lower() for k in (cfg.get("service_keywords") or []) if k}, key=len, reverse=True)
    for kw in keywords:
        if kw and kw in text:
            return f"{kw} help"

    if "shopify" in text:
        return "Shopify help"
    if "landing page" in text:
        return "landing page help"
    if "wordpress" in text:
        return "WordPress help"
    if "website" in text:
        return "website help"
    if "web design" in text:
        return "web design help"
    return "your project"

