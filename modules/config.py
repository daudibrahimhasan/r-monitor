from __future__ import annotations

from pathlib import Path
from typing import Any

from reddit_intent_engine.modules.simple_yaml import load_simple_yaml


def load_config(path: Path) -> dict[str, Any]:
    cfg = load_simple_yaml(path)

    cfg.setdefault("run_mode", "business")

    cfg.setdefault("database", {})
    cfg["database"].setdefault("filename", "leads.sqlite")
    cfg["database"].setdefault("folder", "data")

    cfg.setdefault("exports", {})
    cfg["exports"].setdefault("folder", "data/exports")
    cfg["exports"].setdefault("dated_snapshots", False)

    cfg.setdefault("automation", {})
    cfg["automation"].setdefault("min_score_to_save", 50)
    cfg["automation"].setdefault("min_score_to_draft", 50)
    cfg["automation"].setdefault("min_score_to_auto_send", 50)
    cfg["automation"].setdefault("max_actionable_age_hours", 48)
    cfg["automation"].setdefault("daily_send_limit", 20)
    cfg["automation"].setdefault("followup_after_hours", 48)
    cfg["automation"].setdefault("max_followups", 1)

    cfg.setdefault("reddit", {})
    cfg["reddit"].setdefault("timeout_seconds", 15)
    cfg["reddit"].setdefault("user_agent", "RedditIntentLeadEngine/1.0")
    cfg["reddit"].setdefault("search_queries", [])
    cfg["reddit"].setdefault("max_requests", 40)
    cfg["reddit"].setdefault("search_sort", "new")
    cfg["reddit"].setdefault("search_time_filter", "day")
    cfg["reddit"].setdefault("scan_new_posts", False)
    cfg["reddit"].setdefault("new_limit_per_subreddit", 25)

    cfg.setdefault("email", {})
    cfg["email"].setdefault("enabled", False)
    cfg["email"].setdefault("smtp_server", "smtp.gmail.com")
    cfg["email"].setdefault("smtp_port", 587)
    cfg["email"].setdefault("sender_name", cfg.get("offer", {}).get("sender_name", ""))
    cfg["email"].setdefault("sender_email", cfg.get("offer", {}).get("sender_email", ""))

    cfg.setdefault("subreddits", [])
    cfg.setdefault("service_keywords", [])
    cfg.setdefault("competitors", [])
    cfg.setdefault("intent_phrases", [])
    cfg.setdefault("negative_phrases", [])

    return cfg
