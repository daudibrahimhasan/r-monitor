from __future__ import annotations

from typing import Any

from reddit_intent_engine.modules.database import Database


PERSONAL_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "aol.com",
}


def is_personal_email(email: str) -> bool:
    domain = email.split("@")[-1].lower().strip()
    return domain in PERSONAL_EMAIL_DOMAINS


def can_auto_send(db: Database, contact: dict[str, Any], *, sent_today: int, daily_limit: int) -> bool:
    if not contact:
        return False
    if contact.get("type") != "email":
        return False
    if not contact.get("safe_to_email"):
        return False

    email = str(contact.get("value") or "").lower().strip()
    if not email or "@" not in email:
        return False
    if is_personal_email(email):
        return False
    if db.is_suppressed(email):
        return False
    if db.sent_to_contact_recently(email, days=30):
        return False
    if sent_today >= daily_limit:
        return False
    return True

