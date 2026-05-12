from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from reddit_intent_engine.modules.config import load_config
from reddit_intent_engine.modules.contact_finder import find_safe_contact
from reddit_intent_engine.modules.database import Database
from reddit_intent_engine.modules.email_generator import generate_outreach
from reddit_intent_engine.modules.report import generate_daily_report
from reddit_intent_engine.modules.scorer import score_post


def main() -> int:
    cfg = load_config(Path(__file__).with_name("config.yaml"))

    # Avoid OS temp dirs (can be permission-restricted in some environments).
    base = Path(__file__).resolve().parent / "data" / "_smoke_tmp"
    data_dir = base
    exports_dir = data_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    db = Database(data_dir / "leads.sqlite")
    db.init_db()

    post = {
        "reddit_id": "smoke1",
        "subreddit": "smallbusiness",
        "title": "Anyone got recommendations for a web designer? Budget $1500",
        "body": "Looking for someone ASAP. Email me at hello@acme-example.com or see https://example.com/contact",
        "author": "someone",
        "url": "https://reddit.com/r/smallbusiness/comments/smoke1/test",
        "created_utc": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "num_comments": 0,
        "reddit_score": 0,
        "query": "\"anyone got recommendations for\"",
    }

    s = score_post(post, cfg)
    assert s >= 50, f"expected score >= 50, got {s}"
    post["score"] = s

    post_id = db.save_post(post, status="lead")
    contact = find_safe_contact(post, cfg)
    assert contact and contact["type"] == "email", "expected a safe email contact from post body"
    contact_id = db.save_contact(post_id, contact)

    outreach = generate_outreach(post, cfg, contact=contact)
    assert outreach["subject"] and outreach["body"]
    db.save_outreach(
        post_id=post_id,
        contact_id=contact_id,
        channel="email",
        subject=outreach["subject"],
        body=outreach["body"],
        status="queued_for_review",
        sent_at=None,
        followup_due_at=None,
    )

    report_path = generate_daily_report(db, exports_dir, cfg)
    assert report_path.exists(), "expected report file to be created"
    assert (exports_dir / f"subreddit_sources_{datetime.now(timezone.utc).date().isoformat()}.csv").exists()

    print("SMOKE TEST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
