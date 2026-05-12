from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reddit_intent_engine.modules.config import load_config
from reddit_intent_engine.modules.database import Database
from reddit_intent_engine.modules.email_generator import generate_outreach
from reddit_intent_engine.modules.report import generate_daily_report
from reddit_intent_engine.modules.scorer import score_post


WEB_SEARCH_LEADS: list[dict[str, Any]] = [
    {
        "reddit_id": "1sz293r",
        "subreddit": "smallbusiness",
        "title": "New small business needing website help",
        "body": (
            "I am a small business and am in need of a website. I purchased a domain name, "
            "but don't know where or how to create a website. It is a service business."
        ),
        "author": "",
        "url": "https://www.reddit.com/r/smallbusiness/comments/1sz293r/new_small_business_needing_website_help/",
        "created_utc": "2026-04-29T12:00:00+00:00",
    },
    {
        "reddit_id": "1sl3tz0",
        "subreddit": "GraphicDesignServices",
        "title": "Logo Designer Needed",
        "body": (
            "We're looking for a killer brand designer. Logo/symbol design and basic identity system. "
            "Paid project. DM with portfolio, expected fee, timeline."
        ),
        "author": "",
        "url": "https://www.reddit.com/r/GraphicDesignServices/comments/1sl3tz0/logo_designer_needed/",
        "created_utc": "2026-04-14T12:00:00+00:00",
    },
    {
        "reddit_id": "1s2v4z7",
        "subreddit": "smallbusinessUS",
        "title": "Do small businesses still need a website, or are social pages enough now?",
        "body": (
            "Helping a friend set up a small local business. People keep saying a proper website "
            "is a must if you want to look credible."
        ),
        "author": "",
        "url": "https://www.reddit.com/r/smallbusinessUS/comments/1s2v4z7/do_small_businesses_still_need_a_website_or_are/",
        "created_utc": "2026-03-25T12:00:00+00:00",
    },
    {
        "reddit_id": "1rrya7r",
        "subreddit": "webdesign",
        "title": "Small business website",
        "body": "Small business website discussion with buyers asking about cost and setup.",
        "author": "",
        "url": "https://www.reddit.com/r/webdesign/comments/1rrya7r/small_business_website/",
        "created_utc": "2026-03-13T12:00:00+00:00",
    },
    {
        "reddit_id": "1phyhr7",
        "subreddit": "shopify",
        "title": "Finding a Shopify Web Developer",
        "body": "Looking for help finding a Shopify web developer.",
        "author": "",
        "url": "https://www.reddit.com/r/shopify/comments/1phyhr7/finding_a_shopify_web_developer/",
        "created_utc": "2025-12-01T12:00:00+00:00",
    },
    {
        "reddit_id": "1pi1ncd",
        "subreddit": "smallbusiness",
        "title": "Where are people getting their logos from?",
        "body": "First time business owner. I have no idea where to begin with coming up with a business logo.",
        "author": "",
        "url": "https://www.reddit.com/r/smallbusiness/comments/1pi1ncd/where_are_people_getting_their_logos_from/",
        "created_utc": "2025-12-09T12:00:00+00:00",
    },
    {
        "reddit_id": "1pd9kqs",
        "subreddit": "smallbusiness",
        "title": "Website needed. Help",
        "body": "Trying to create websites myself, but it looks like a PowerPoint presentation. Need website help.",
        "author": "",
        "url": "https://www.reddit.com/r/smallbusiness/comments/1pd9kqs/website_needed_help/",
        "created_utc": "2025-12-03T12:00:00+00:00",
    },
    {
        "reddit_id": "1n65txb",
        "subreddit": "webdesign",
        "title": "Looking For Web Designer",
        "body": "Let me know if you're interested. We can talk about pay and availability.",
        "author": "",
        "url": "https://www.reddit.com/r/webdesign/comments/1n65txb/looking_for_web_designer/",
        "created_utc": "2025-09-02T12:00:00+00:00",
    },
    {
        "reddit_id": "1jp37os",
        "subreddit": "smallbusiness",
        "title": "Need logo design for homestead/farm",
        "body": "Need a logo for a small homestead. Need tweaks and correct file type and dimensions.",
        "author": "",
        "url": "https://www.reddit.com/r/smallbusiness/comments/1jp37os/need_logo_design_for_homesteadfarm/",
        "created_utc": "2025-04-01T12:00:00+00:00",
    },
    {
        "reddit_id": "1iazhpz",
        "subreddit": "smallbusiness",
        "title": "I need a website",
        "body": "I need a simple website for my mom's house cleaning business. Photos, reviews, prices, scheduling estimate.",
        "author": "",
        "url": "https://www.reddit.com/r/smallbusiness/comments/1iazhpz/i_need_a_website/",
        "created_utc": "2025-01-27T12:00:00+00:00",
    },
]


def seed(config_path: Path) -> int:
    cfg = load_config(config_path)
    base_dir = config_path.parent
    data_dir = base_dir / "data"
    exports_dir = data_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    db = Database(data_dir / str(cfg.get("database", {}).get("filename") or "leads.sqlite"))
    db.init_db()

    created = 0
    for post in WEB_SEARCH_LEADS:
        if db.post_exists(url=post["url"], reddit_id=post["reddit_id"]):
            continue
        post = dict(post)
        post["score"] = score_post(post, cfg)
        status = "lead" if int(post["score"]) >= int(cfg.get("automation", {}).get("min_score_to_save", 50)) else "research_candidate"
        post_id = db.save_post(post, status=status)
        outreach = generate_outreach(post, cfg, contact=None)
        db.save_outreach(
            post_id=post_id,
            contact_id=None,
            channel="manual_review",
            subject=outreach["subject"],
            body=outreach["body"],
            status="web_research_review",
            sent_at=None,
            followup_due_at=None,
        )
        created += 1

    generate_daily_report(db, exports_dir, cfg)
    print(f"Seeded {created} web-research leads at {datetime.now(timezone.utc).isoformat()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed verified web-search Reddit leads into the local database.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    return seed(Path(args.config).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
