from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path

from reddit_intent_engine.modules.database import Database


RESEARCH_EXPORT_PHRASES = [
    "collaborat",
    "co-author",
    "research partner",
    "research assistant",
    "research intern",
    "joint paper",
    "working on a paper",
    "writing a paper",
    "need help with research",
    "need help with experiments",
    "need implementation help",
    "looking for help with paper",
    "need feedback on paper",
    "peer review",
    "submitting to",
    "paper submission",
]

RESEARCH_CONTEXT_TERMS = [
    "paper",
    "research",
    "conference",
    "workshop",
    "journal",
    "review",
    "rebuttal",
    "experiment",
    "dataset",
    "benchmark",
    "professor",
    "phd",
    "arxiv",
    "neurips",
    "iclr",
    "icml",
    "acl",
    "tmlr",
]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _age_label(created_utc: str | None, now: datetime) -> str:
    created = _parse_dt(created_utc)
    if not created:
        return ""
    seconds = max(0, int((now - created).total_seconds()))
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _posted_text(created_utc: str | None) -> str:
    created = _parse_dt(created_utc)
    if not created:
        return ""
    return created.strftime("%Y-%m-%d %H:%M UTC")


def _age_hours(created_utc: str | None, now: datetime) -> float | None:
    created = _parse_dt(created_utc)
    if not created:
        return None
    return max(0, (now - created).total_seconds() / 3600)


def _recommended_action(row: dict) -> str:
    if str(row.get("safe_to_email") or "0") == "1" and row.get("contact_value"):
        return "send safe business email"
    if row.get("outreach_status"):
        return "review draft and reply/DM on Reddit"
    return "open post and decide manually"


def _is_hot_lead_candidate(row: dict) -> bool:
    title = str(row.get("title") or "").lower()
    text = f"{title} {str(row.get('research_topic') or '').lower()}"
    seller_markers = [
        "[for hire]",
        "for hire",
        "i'll create",
        "i will create",
        "offering",
        "my experience",
        "i built",
        "we built",
        "built a",
        "launched",
        "free tool",
        "case study",
        "we helped",
        "senior graphic designer",
    ]
    if any(marker in text for marker in seller_markers):
        return False

    buyer_markers = [
        "[hiring]",
        "hiring",
        "looking for",
        "need ",
        "need help",
        "help me",
        "issue",
        "problem",
        "not working",
        "low budget",
        "high cpc",
        "drop-off",
        "drop off",
        "review",
        "criticism",
        "how do i",
        "can't",
        "confused",
    ]
    return any(marker in text for marker in buyer_markers)


def generate_daily_report(db: Database, exports_dir: Path, cfg: dict | None = None) -> Path:
    run_mode = str((cfg or {}).get("run_mode") or "business").lower()
    if run_mode == "research":
        return generate_research_report(db, exports_dir)

    now = datetime.now(timezone.utc)
    leads = db.get_today_leads(now_utc=now)
    all_leads = db.get_all_leads(limit=10000)
    max_actionable_age_hours = int((cfg or {}).get("automation", {}).get("max_actionable_age_hours", 48))
    dated_snapshots = bool((cfg or {}).get("exports", {}).get("dated_snapshots", False))

    date_str = now.date().isoformat()
    md_path = exports_dir / "daily_report_current.md"
    csv_path = exports_dir / "daily_report_current.csv"
    hot_leads_csv_path = exports_dir / "hot_leads_current.csv"
    all_leads_csv_path = exports_dir / "all_leads_current.csv"
    drafts_csv_path = exports_dir / "drafts_current.csv"
    lead_sheet_md_path = exports_dir / "leads_current.md"
    lead_sheet_csv_path = exports_dir / "leads_current.csv"
    stale_md_path = exports_dir / "stale_leads_current.md"
    stale_csv_path = exports_dir / "stale_leads_current.csv"
    review_path = exports_dir / "review_queue_current.md"
    sources_md_path = exports_dir / "subreddit_sources_current.md"
    sources_csv_path = exports_dir / "subreddit_sources_current.csv"

    lines: list[str] = []
    lines.append("# Daily Reddit Intent Report")
    lines.append("")
    for lead in leads:
        lines.append(f"Score: {lead['score']}")
        lines.append(f"Subreddit: r/{lead['subreddit']}")
        lines.append(f"Title: {lead['title']}")
        lines.append(f"URL: {lead['url']}")
        lines.append(f"Status: {lead['status']}")
        lines.append("---")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["score", "subreddit", "title", "url", "posted_at", "age", "status", "found_at"])
        w.writeheader()
        for lead in leads:
            w.writerow(
                {
                    "score": lead["score"],
                    "subreddit": lead["subreddit"],
                    "title": lead["title"],
                    "url": lead["url"],
                    "posted_at": lead.get("created_utc"),
                    "age": _age_label(lead.get("created_utc"), now),
                    "status": lead["status"],
                    "found_at": lead["found_at"],
                }
            )

    all_lead_fields = [
        "posted_at_utc",
        "age",
        "age_hours",
        "found_at",
        "score",
        "lead_status",
        "subreddit",
        "subreddit_url",
        "title",
        "post_url",
        "author",
        "research_topic",
        "contact_type",
        "contact_value",
        "safe_to_email",
        "outreach_status",
    ]
    all_lead_rows = []
    for lead in all_leads:
        subreddit = str(lead.get("subreddit") or "")
        hours_old = _age_hours(lead.get("created_utc"), now)
        all_lead_rows.append(
            {
                "posted_at_utc": _posted_text(lead.get("created_utc")),
                "age": _age_label(lead.get("created_utc"), now),
                "age_hours": round(hours_old, 1) if hours_old is not None else "",
                "found_at": lead.get("found_at") or "",
                "score": lead.get("score"),
                "lead_status": lead.get("status") or "",
                "subreddit": f"r/{subreddit}",
                "subreddit_url": f"https://www.reddit.com/r/{subreddit}/",
                "title": lead.get("title") or "",
                "post_url": lead.get("url") or "",
                "author": lead.get("author") or "",
                "research_topic": lead.get("research_topic") or "",
                "contact_type": lead.get("contact_type") or "",
                "contact_value": lead.get("contact_value") or "",
                "safe_to_email": int(lead.get("safe_to_email") or 0),
                "outreach_status": lead.get("outreach_status") or "",
            }
        )

    run_started_at = _parse_dt(str((cfg or {}).get("_run_started_at") or ""))
    hot_min_score = int((cfg or {}).get("automation", {}).get("min_score_to_draft", 50))
    hot_candidates = [
        row
        for row in all_lead_rows
        if row["age_hours"] != ""
        and float(row["age_hours"]) <= max_actionable_age_hours
        and int(row["score"] or 0) >= hot_min_score
        and _is_hot_lead_candidate(row)
    ]
    top_hot_rows = sorted(
        hot_candidates,
        key=lambda row: (-int(row["score"] or 0), float(row["age_hours"] or 999999), str(row["posted_at_utc"])),
    )[:10]
    top_hot_urls = {str(row["post_url"]) for row in top_hot_rows}
    new_hot_rows = []
    if run_started_at:
        for row in sorted(hot_candidates, key=lambda row: str(row["posted_at_utc"]), reverse=True):
            found_at = _parse_dt(str(row.get("found_at") or ""))
            if found_at and found_at >= run_started_at and str(row["post_url"]) not in top_hot_urls:
                new_hot_rows.append(row)

    hot_fields = [
        "hot_rank",
        "hot_group",
        "posted_at_utc",
        "age",
        "age_hours",
        "found_at",
        "score",
        "lead_status",
        "subreddit",
        "subreddit_url",
        "title",
        "post_url",
        "author",
        "contact_type",
        "contact_value",
        "safe_to_email",
        "outreach_status",
        "recommended_action",
    ]
    with hot_leads_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=hot_fields)
        w.writeheader()
        rank = 1
        for row in top_hot_rows:
            hot_row = dict(row)
            hot_row["hot_rank"] = rank
            hot_row["hot_group"] = "top10"
            hot_row["recommended_action"] = _recommended_action(hot_row)
            w.writerow({field: hot_row.get(field, "") for field in hot_fields})
            rank += 1
        for row in new_hot_rows:
            hot_row = dict(row)
            hot_row["hot_rank"] = rank
            hot_row["hot_group"] = "new_hot_this_run"
            hot_row["recommended_action"] = _recommended_action(hot_row)
            w.writerow({field: hot_row.get(field, "") for field in hot_fields})
            rank += 1

    with all_leads_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_lead_fields)
        w.writeheader()
        for row in all_lead_rows:
            w.writerow(row)

    draft_fields = [
        "posted_at_utc",
        "age",
        "age_hours",
        "score",
        "lead_status",
        "outreach_status",
        "channel",
        "subreddit",
        "subreddit_url",
        "title",
        "post_url",
        "author",
        "contact_type",
        "contact_value",
        "safe_to_email",
        "subject",
        "body",
        "sent_at",
        "followup_due_at",
        "followup_sent",
        "replied",
        "opted_out",
    ]
    draft_rows = []
    for draft in db.get_all_drafts(limit=5000):
        subreddit = str(draft.get("subreddit") or "")
        hours_old = _age_hours(draft.get("created_utc"), now)
        draft_rows.append(
            {
                "posted_at_utc": _posted_text(draft.get("created_utc")),
                "age": _age_label(draft.get("created_utc"), now),
                "age_hours": round(hours_old, 1) if hours_old is not None else "",
                "score": draft.get("score"),
                "lead_status": draft.get("lead_status") or "",
                "outreach_status": draft.get("outreach_status") or "",
                "channel": draft.get("channel") or "",
                "subreddit": f"r/{subreddit}",
                "subreddit_url": f"https://www.reddit.com/r/{subreddit}/",
                "title": draft.get("title") or "",
                "post_url": draft.get("url") or "",
                "author": draft.get("author") or "",
                "contact_type": draft.get("contact_type") or "",
                "contact_value": draft.get("contact_value") or "",
                "safe_to_email": int(draft.get("safe_to_email") or 0),
                "subject": draft.get("subject") or "",
                "body": draft.get("body") or "",
                "sent_at": draft.get("sent_at") or "",
                "followup_due_at": draft.get("followup_due_at") or "",
                "followup_sent": int(draft.get("followup_sent") or 0),
                "replied": int(draft.get("replied") or 0),
                "opted_out": int(draft.get("opted_out") or 0),
            }
        )

    with drafts_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=draft_fields)
        w.writeheader()
        for row in draft_rows:
            w.writerow(row)

    lead_fields = [
        "posted_at_utc",
        "age",
        "age_hours",
        "score",
        "subreddit",
        "subreddit_url",
        "title",
        "post_url",
        "contact_type",
        "contact_value",
        "safe_to_email",
        "outreach_status",
    ]
    lead_sheet_rows = []
    stale_rows = []
    for lead in all_leads:
        subreddit = str(lead.get("subreddit") or "")
        hours_old = _age_hours(lead.get("created_utc"), now)
        row = {
            "posted_at_utc": _posted_text(lead.get("created_utc")),
            "age": _age_label(lead.get("created_utc"), now),
            "age_hours": round(hours_old, 1) if hours_old is not None else "",
            "score": lead.get("score"),
            "subreddit": f"r/{subreddit}",
            "subreddit_url": f"https://www.reddit.com/r/{subreddit}/",
            "title": lead.get("title") or "",
            "post_url": lead.get("url") or "",
            "contact_type": lead.get("contact_type") or "",
            "contact_value": lead.get("contact_value") or "",
            "safe_to_email": int(lead.get("safe_to_email") or 0),
            "outreach_status": lead.get("outreach_status") or "",
        }
        if hours_old is not None and hours_old <= max_actionable_age_hours:
            lead_sheet_rows.append(row)
        else:
            stale_rows.append(row)

    with lead_sheet_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=lead_fields)
        w.writeheader()
        for row in lead_sheet_rows:
            w.writerow(row)

    lead_lines = ["# Leads Sorted By Post Time", ""]
    lead_lines.append(f"Actionable window: {max_actionable_age_hours} hours")
    lead_lines.append("")
    lead_lines.append("| Posted | Age | Score | Subreddit | Title | Link | Contact | Outreach |")
    lead_lines.append("|---|---:|---:|---|---|---|---|---|")
    for row in lead_sheet_rows:
        title = str(row["title"]).replace("|", "\\|")
        contact = str(row["contact_value"] or row["contact_type"] or "").replace("|", "\\|")
        lead_lines.append(
            f"| {row['posted_at_utc']} | {row['age']} | {row['score']} | "
            f"[{row['subreddit']}]({row['subreddit_url']}) | {title} | "
            f"[post]({row['post_url']}) | {contact} | {row['outreach_status']} |"
        )
    lead_sheet_md_path.write_text("\n".join(lead_lines) + "\n", encoding="utf-8")

    with stale_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=lead_fields)
        w.writeheader()
        for row in stale_rows:
            w.writerow(row)

    stale_lines = ["# Stale Leads Archive", ""]
    stale_lines.append(f"Rows older than {max_actionable_age_hours} hours")
    stale_lines.append("")
    stale_lines.append("| Posted | Age | Score | Subreddit | Title | Link |")
    stale_lines.append("|---|---:|---:|---|---|---|")
    for row in stale_rows:
        title = str(row["title"]).replace("|", "\\|")
        stale_lines.append(
            f"| {row['posted_at_utc']} | {row['age']} | {row['score']} | "
            f"[{row['subreddit']}]({row['subreddit_url']}) | {title} | [post]({row['post_url']}) |"
        )
    stale_md_path.write_text("\n".join(stale_lines) + "\n", encoding="utf-8")

    review_lines: list[str] = []
    review_lines.append("# Review Queue")
    review_lines.append("")
    for item in db.iter_review_queue(limit=200):
        review_lines.append(f"Score: {item['score']}")
        review_lines.append(f"Status: {item['status']}")
        review_lines.append(f"Subreddit: r/{item['subreddit']}")
        review_lines.append(f"Title: {item['title']}")
        review_lines.append(f"URL: {item['url']}")
        review_lines.append("")
        review_lines.append("Draft:")
        review_lines.append("")
        review_lines.append(item["body"])
        review_lines.append("")
        review_lines.append("---")
    review_path.write_text("\n".join(review_lines) + "\n", encoding="utf-8")

    subreddit_names = list((cfg or {}).get("subreddits") or [])
    counts = db.get_lead_counts_by_subreddit(now_utc=now)
    source_rows = []
    for subreddit in subreddit_names:
        subreddit = str(subreddit)
        count = counts.get(subreddit, {"today": 0, "total": 0})
        source_rows.append(
            {
                "subreddit": subreddit,
                "url": f"https://www.reddit.com/r/{subreddit}/",
                "today_leads": count["today"],
                "total_leads": count["total"],
            }
        )

    source_lines = ["# Subreddit Lead Sources", ""]
    source_lines.append("| Subreddit | URL | Today Leads | Total Leads |")
    source_lines.append("|---|---:|---:|---:|")
    for row in source_rows:
        source_lines.append(
            f"| r/{row['subreddit']} | {row['url']} | {row['today_leads']} | {row['total_leads']} |"
        )
    sources_md_path.write_text("\n".join(source_lines) + "\n", encoding="utf-8")

    with sources_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["subreddit", "url", "today_leads", "total_leads"])
        w.writeheader()
        for row in source_rows:
            w.writerow(row)

    if dated_snapshots:
        for current_path, snapshot_path in [
            (md_path, exports_dir / f"daily_report_{date_str}.md"),
            (csv_path, exports_dir / f"daily_report_{date_str}.csv"),
            (hot_leads_csv_path, exports_dir / f"hot_leads_{date_str}.csv"),
            (all_leads_csv_path, exports_dir / f"all_leads_{date_str}.csv"),
            (drafts_csv_path, exports_dir / f"drafts_{date_str}.csv"),
            (lead_sheet_md_path, exports_dir / f"leads_sorted_{date_str}.md"),
            (lead_sheet_csv_path, exports_dir / f"leads_sorted_{date_str}.csv"),
            (stale_md_path, exports_dir / f"stale_leads_{date_str}.md"),
            (stale_csv_path, exports_dir / f"stale_leads_{date_str}.csv"),
            (review_path, exports_dir / f"review_queue_{date_str}.md"),
            (sources_md_path, exports_dir / f"subreddit_sources_{date_str}.md"),
            (sources_csv_path, exports_dir / f"subreddit_sources_{date_str}.csv"),
        ]:
            shutil.copyfile(current_path, snapshot_path)

    return md_path


def generate_research_report(db: Database, exports_dir: Path) -> Path:
    leads = [lead for lead in db.get_research_leads(limit=500) if _is_curated_research_lead(lead)]
    md_path = exports_dir / "research_leads.md"
    csv_path = exports_dir / "research_leads.csv"

    lines = [
        "# Research Leads",
        "",
        "| Post Title | Subreddit | Author | URL | Research Topic | Score | Outreach Draft |",
        "|---|---|---|---|---|---:|---|",
    ]
    for lead in leads:
        title = str(lead.get("title") or "").replace("|", "\\|")
        subreddit = f"r/{str(lead.get('subreddit') or '').replace('|', '\\|')}"
        author = str(lead.get("author") or "").replace("|", "\\|")
        url = str(lead.get("url") or "")
        topic = str(lead.get("research_topic") or "").replace("|", "\\|")
        draft = str(lead.get("outreach_body") or "").replace("\r\n", "\n").replace("\n", "<br>").replace("|", "\\|")
        lines.append(f"| {title} | {subreddit} | {author} | {url} | {topic} | {lead.get('score') or 0} | {draft} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["post_title", "subreddit", "author", "url", "research_topic", "score", "outreach_draft"],
        )
        writer.writeheader()
        for lead in leads:
            writer.writerow(
                {
                    "post_title": lead.get("title") or "",
                    "subreddit": lead.get("subreddit") or "",
                    "author": lead.get("author") or "",
                    "url": lead.get("url") or "",
                    "research_topic": lead.get("research_topic") or "",
                    "score": lead.get("score") or 0,
                    "outreach_draft": lead.get("outreach_body") or "",
                }
            )

    return md_path


def _is_curated_research_lead(lead: dict) -> bool:
    score = int(lead.get("score") or 0)
    if score < 30:
        return False
    text = f"{lead.get('title') or ''} {lead.get('body') or ''}".lower()
    has_intent = any(phrase in text for phrase in RESEARCH_EXPORT_PHRASES)
    has_context = any(term in text for term in RESEARCH_CONTEXT_TERMS)
    return has_intent and has_context
