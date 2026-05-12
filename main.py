from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from reddit_intent_engine.modules.config import load_config
from reddit_intent_engine.modules.contact_finder import find_safe_contact
from reddit_intent_engine.modules.database import Database
from reddit_intent_engine.modules.email_generator import generate_outreach
from reddit_intent_engine.modules.email_sender import EmailSender
from reddit_intent_engine.modules.reddit_search import search_reddit
from reddit_intent_engine.modules.report import generate_daily_report
from reddit_intent_engine.modules.safety import can_auto_send
from reddit_intent_engine.modules.scorer import score_post


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Reddit Intent Lead Engine")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.yaml")),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send emails (requires email.enabled: true)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Override reddit.max_requests for this run",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Override reddit.timeout_seconds for this run",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    cfg["_run_started_at"] = datetime.now(timezone.utc).isoformat()
    if args.max_requests is not None:
        cfg.setdefault("reddit", {})
        cfg["reddit"]["max_requests"] = int(args.max_requests)
    if args.timeout_seconds is not None:
        cfg.setdefault("reddit", {})
        cfg["reddit"]["timeout_seconds"] = int(args.timeout_seconds)

    base_dir = config_path.parent
    run_mode = str(cfg.get("run_mode") or "business").lower()
    data_folder = str(cfg.get("database", {}).get("folder") or "data")
    exports_folder = str(cfg.get("exports", {}).get("folder") or "data/exports")
    data_dir = (base_dir / data_folder).resolve()
    exports_dir = (base_dir / exports_folder).resolve()
    exports_dir.mkdir(parents=True, exist_ok=True)

    _setup_logging(data_dir / "logs.txt")

    db_filename = str(cfg.get("database", {}).get("filename") or "leads.sqlite")
    db = Database(data_dir / db_filename)
    db.init_db()

    logging.info("Searching Reddit for %s leads...", run_mode)
    posts = search_reddit(cfg)
    logging.info("Found %d raw results", len(posts))

    min_score = int(cfg["automation"]["min_score_to_save"])
    min_score_to_draft = int(cfg["automation"].get("min_score_to_draft", min_score))
    min_score_to_auto_send = int(cfg["automation"].get("min_score_to_auto_send", 50))
    daily_limit = int(cfg["automation"]["daily_send_limit"])

    email_sender = EmailSender.from_config(cfg)
    sending_enabled = bool(cfg.get("email", {}).get("enabled")) and bool(args.send)

    leads_created = 0
    drafts_created = 0
    emails_sent = 0

    for post in posts:
        post["research_topic"] = str(post.get("query") or "")
        if db.post_exists(url=post["url"], reddit_id=post["reddit_id"]):
            continue

        score = score_post(post, cfg)
        post["score"] = score

        if score < min_score:
            db.save_post(post, status="ignored" if run_mode == "business" else "research_ignored")
            continue

        post_id = db.save_post(post, status="lead" if run_mode == "business" else "research_candidate")
        leads_created += 1

        if run_mode == "research":
            if score < min_score_to_draft:
                continue
            outreach = generate_outreach(post, cfg, contact=None)
            drafts_created += 1
            db.save_outreach(
                post_id=post_id,
                contact_id=None,
                channel="research",
                subject=outreach["subject"],
                body=outreach["body"],
                status="research_draft",
                sent_at=None,
                followup_due_at=None,
            )
            continue

        if score < min_score_to_draft:
            continue

        contact = find_safe_contact(post, cfg)

        contact_id = None
        if contact:
            contact_id = db.save_contact(post_id, contact)

        outreach = generate_outreach(post, cfg, contact=contact)
        drafts_created += 1

        sent_today = db.count_sent_today(datetime.now(timezone.utc))

        if (
            sending_enabled
            and score >= min_score_to_auto_send
            and contact
            and can_auto_send(db, contact, sent_today=sent_today, daily_limit=daily_limit)
        ):
            email_sender.send_email(
                to_email=contact["value"],
                subject=outreach["subject"],
                body=outreach["body"],
            )
            db.save_outreach(
                post_id=post_id,
                contact_id=contact_id,
                channel="email",
                subject=outreach["subject"],
                body=outreach["body"],
                status="sent",
                sent_at=datetime.now(timezone.utc),
                followup_due_at=db.compute_followup_due_at(cfg),
            )
            emails_sent += 1
        else:
            status = "queued_for_review"
            channel = "manual_review"
            if not contact:
                status = "no_safe_contact_found"
            elif contact["type"] == "reddit_review":
                status = "reddit_reply_or_dm_review"

            if score < min_score_to_auto_send:
                status = "below_auto_send_threshold"

            db.save_outreach(
                post_id=post_id,
                contact_id=contact_id,
                channel=channel,
                subject=outreach["subject"],
                body=outreach["body"],
                status=status,
                sent_at=None,
                followup_due_at=None,
            )

    report_path = generate_daily_report(db, exports_dir, cfg)
    logging.info("Leads created: %d | Drafts: %d | Emails sent: %d", leads_created, drafts_created, emails_sent)
    logging.info("Daily report: %s", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
