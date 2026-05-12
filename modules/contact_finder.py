from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# Reuse the same concept of a shared executor for network tasks
_CONTACT_EXECUTOR = ThreadPoolExecutor(max_workers=50)


EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

BLOCKED_EMAIL_PREFIXES = [
    "abuse@",
    "privacy@",
    "security@",
    "noreply@",
    "no-reply@",
]


def find_safe_contact(post: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    text = f"{post.get('title','')} {post.get('body','')}"

    direct_emails = extract_emails(text)
    if direct_emails:
        return {
            "type": "email",
            "value": direct_emails[0],
            "source_url": post.get("url", ""),
            "safe_to_email": True,
            "reason": "Email was publicly included in the post",
        }

    urls = extract_urls(text)
    for url in urls:
        contact = find_contact_on_website(url, timeout_seconds=int(cfg.get("reddit", {}).get("timeout_seconds", 10)))
        if contact:
            return contact

    if explicit_contact_allowed(text):
        return {
            "type": "reddit_review",
            "value": post.get("url", ""),
            "source_url": post.get("url", ""),
            "safe_to_email": False,
            "reason": "Poster invited contact, but Reddit message should be reviewed manually",
        }

    return None


def extract_emails(text: str) -> list[str]:
    emails = re.findall(EMAIL_REGEX, text)
    clean: list[str] = []
    for email in emails:
        lower = email.lower()
        if any(lower.startswith(prefix) for prefix in BLOCKED_EMAIL_PREFIXES):
            continue
        if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            continue
        clean.append(email)
    # Stable order unique
    seen: set[str] = set()
    out: list[str] = []
    for e in clean:
        el = e.lower()
        if el in seen:
            continue
        seen.add(el)
        out.append(e)
    return out


def extract_urls(text: str) -> list[str]:
    # Common, safe-ish extraction; excludes trailing punctuation/brackets.
    return re.findall(r"https?://[^\s\)\]\}<>\"']+", text)


def explicit_contact_allowed(text: str) -> bool:
    t = text.lower()
    phrases = ["dm me", "message me", "contact me", "reach out", "send me", "email me"]
    return any(p in t for p in phrases)


def find_contact_on_website(url: str, *, timeout_seconds: int = 10) -> dict[str, Any] | None:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; RedditIntentLeadEngine/1.0)"}

    def _get_emails(target_url: str) -> list[str]:
        try:
            r = requests.get(target_url, timeout=timeout_seconds, headers=headers, allow_redirects=True)
            if r.status_code == 200:
                return extract_emails(r.text)
        except Exception:
            pass
        return []

    try:
        resp = requests.get(url, timeout=timeout_seconds, headers=headers, allow_redirects=True)
        if resp.status_code != 200:
            return None

        emails = extract_emails(resp.text)
        if emails:
            return {
                "type": "email",
                "value": emails[0],
                "source_url": url,
                "safe_to_email": True,
                "reason": "Email was found on a publicly linked website",
            }

        soup = BeautifulSoup(resp.text, "html.parser")
        contact_links: list[set] = []
        seen_links = {url.rstrip("/")}
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            full_url = urljoin(url, href).split("#")[0].rstrip("/")
            if full_url in seen_links:
                continue

            href_low = href.lower()
            text_low = a.get_text(" ").lower()
            if "contact" in href_low or "contact" in text_low:
                contact_links.append(full_url)
                seen_links.add(full_url)

        if not contact_links:
            return None

        # Parallelize checking the contact pages
        futures = {
            _CONTACT_EXECUTOR.submit(_get_emails, contact_url): contact_url
            for contact_url in contact_links[:5]
        }
        for fut in as_completed(futures):
            found_emails = fut.result()
            if found_emails:
                return {
                    "type": "email",
                    "value": found_emails[0],
                    "source_url": futures[fut],
                    "safe_to_email": True,
                    "reason": "Email was found on a public contact page",
                }
    except Exception:
        return None

    return None

