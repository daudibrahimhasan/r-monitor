from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from reddit_intent_engine.modules.config import load_config
from reddit_intent_engine.modules.database import Database
from reddit_intent_engine.modules.email_sender import EmailSender


FOLLOWUP_TEMPLATE = """Hey,

Quick follow-up on my note.

Based on the Reddit post, the first thing I’d check is whether the issue is the page structure, offer clarity, or actual design.

Happy to send 2–3 quick suggestions if useful.

Best,
{sender_name}

P.S. Reply “no” and I will not follow up.
"""


def run_followups(*, config_path: Path, send: bool) -> int:
    cfg = load_config(config_path)
    base_dir = config_path.parent
    data_dir = (base_dir / "data").resolve()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db_filename = str(cfg.get("database", {}).get("filename") or "leads.sqlite")
    db = Database(data_dir / db_filename)
    db.init_db()

    max_followups = int(cfg.get("automation", {}).get("max_followups", 1))
    if max_followups <= 0:
        logging.info("Follow-ups disabled (max_followups <= 0)")
        return 0

    sender = EmailSender.from_config(cfg)
    sending_enabled = bool(cfg.get("email", {}).get("enabled")) and bool(send)
    if not sending_enabled:
        logging.info("Send disabled; skipping follow-up sends (use email.enabled + --send)")
        return 0

    candidates = db.get_followup_candidates(
        now_utc=datetime.now(timezone.utc),
        min_age_hours=int(cfg.get("automation", {}).get("followup_after_hours", 48)),
    )
    logging.info("Follow-up candidates: %d", len(candidates))

    for lead in candidates:
        subject = "Re: " + str(lead.get("subject") or "").strip()
        body = FOLLOWUP_TEMPLATE.format(sender_name=str(cfg.get("offer", {}).get("sender_name") or "Your Name"))

        sender.send_email(to_email=lead["email"], subject=subject, body=body)
        db.mark_followup_sent(int(lead["outreach_id"]))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Send follow-ups for sent outreach.")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--send", action="store_true", help="Actually send followups (requires email.enabled: true)")
    args = parser.parse_args()
    return run_followups(config_path=Path(args.config).resolve(), send=bool(args.send))


if __name__ == "__main__":
    raise SystemExit(main())
