from __future__ import annotations

import logging
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class RedditSearchSettings:
    user_agent: str
    timeout_seconds: int


def _build_queries(cfg: dict[str, Any]) -> list[str]:
    explicit = list(cfg.get("reddit", {}).get("search_queries") or [])
    if explicit:
        return explicit

    # Simple generator: pair a few intent phrases with top service keywords.
    intents = [p for p in (cfg.get("intent_phrases") or []) if p]
    keywords = [k for k in (cfg.get("service_keywords") or []) if k]
    intents = intents[:8] if intents else ["looking for", "recommend", "hire", "urgent"]
    keywords = keywords[:8] if keywords else ["website", "web design", "wordpress", "shopify"]
    queries: list[str] = []
    for intent in intents:
        for kw in keywords[:3]:
            queries.append(f"\"{intent}\" \"{kw}\"")
    return queries[:60]


def search_reddit(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    subreddits = cfg.get("subreddits") or []
    reddit_cfg = cfg.get("reddit", {}) or {}
    settings = RedditSearchSettings(
        user_agent=str(reddit_cfg.get("user_agent") or "RedditIntentLeadEngine/1.0"),
        timeout_seconds=int(reddit_cfg.get("timeout_seconds") or 15),
    )
    headers = {"User-Agent": settings.user_agent}
    queries = _build_queries(cfg)
    mr = reddit_cfg.get("max_requests", 40)
    max_requests = int(mr) if mr is not None else 40
    search_sort = str(reddit_cfg.get("search_sort") or "new")
    search_time_filter = str(reddit_cfg.get("search_time_filter") or "day")

    results: list[dict[str, Any]] = []

    req_count = 0
    if bool(reddit_cfg.get("scan_new_posts")):
        new_limit = int(reddit_cfg.get("new_limit_per_subreddit") or 25)
        for subreddit in subreddits:
            if req_count >= max_requests:
                break
            try:
                fresh_posts = _fetch_subreddit_new(
                    subreddit=str(subreddit),
                    headers=headers,
                    timeout_seconds=settings.timeout_seconds,
                    limit=new_limit,
                )
                req_count += 1
                results.extend(fresh_posts)
            except Exception:
                continue
            time.sleep(0.1)

    for subreddit in subreddits:
        for query in queries:
            if req_count >= max_requests:
                break
            encoded_query = urllib.parse.quote(query)
            url = (
                f"https://www.reddit.com/r/{subreddit}/search.json"
                f"?q={encoded_query}&restrict_sr=1&sort={urllib.parse.quote(search_sort)}&t={urllib.parse.quote(search_time_filter)}&raw_json=1"
            )

            try:
                resp = _safe_get(url, headers=headers, timeout_seconds=settings.timeout_seconds)
                req_count += 1
                if resp is None:
                    continue
                if resp.status_code == 429:
                    time.sleep(2.5)
                    continue
                if resp.status_code != 200:
                    # Reddit sometimes blocks JSON endpoints; fall back to RSS.
                    rss_results = _search_rss(
                        subreddit=str(subreddit),
                        query=str(query),
                        headers=headers,
                        timeout_seconds=settings.timeout_seconds,
                        search_sort=search_sort,
                        search_time_filter=search_time_filter,
                    )
                    if rss_results:
                        results.extend(rss_results)
                    continue

                data = resp.json()
                children = data.get("data", {}).get("children", []) or []
                for item in children:
                    p = item.get("data", {}) or {}
                    created = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)
                    permalink = p.get("permalink") or ""

                    results.append(
                        {
                            "reddit_id": p.get("id"),
                            "subreddit": str(p.get("subreddit") or subreddit),
                            "title": p.get("title", "") or "",
                            "body": p.get("selftext", "") or "",
                            "author": p.get("author", "") or "",
                            "url": ("https://reddit.com" + permalink) if permalink.startswith("/") else str(p.get("url") or ""),
                            "created_utc": created.isoformat(),
                            "num_comments": int(p.get("num_comments") or 0),
                            "reddit_score": int(p.get("score") or 0),
                            "query": query,
                        }
                    )
            except Exception as exc:
                # JSON parse / transient network issue -> RSS fallback
                logging.debug("search.json failed for r/%s query %r: %s", subreddit, query, exc)
                try:
                    rss_results = _search_rss(
                        subreddit=str(subreddit),
                        query=str(query),
                        headers=headers,
                        timeout_seconds=settings.timeout_seconds,
                        search_sort=search_sort,
                        search_time_filter=search_time_filter,
                    )
                    if rss_results:
                        results.extend(rss_results)
                except Exception as rss_exc:
                    logging.debug("RSS fallback failed for r/%s query %r: %s", subreddit, query, rss_exc)
                    pass
                continue

            time.sleep(0.2)
        if req_count >= max_requests:
            break

    # De-dupe by URL, keep newest seen first.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for p in results:
        u = p.get("url") or ""
        if not u or u in seen:
            continue
        seen.add(u)
        deduped.append(p)

    return deduped


def _fetch_subreddit_new(
    *,
    subreddit: str,
    headers: dict[str, str],
    timeout_seconds: int,
    limit: int,
) -> list[dict[str, Any]]:
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={int(limit)}&raw_json=1"
    resp = _safe_get(url, headers=headers, timeout_seconds=timeout_seconds)
    if resp is None or resp.status_code != 200:
        return []

    data = resp.json()
    out: list[dict[str, Any]] = []
    for item in data.get("data", {}).get("children", []) or []:
        post_data = item.get("data", {}) or {}
        created = datetime.fromtimestamp(post_data.get("created_utc", 0), tz=timezone.utc)
        permalink = post_data.get("permalink") or ""
        out.append(
            {
                "reddit_id": post_data.get("id"),
                "subreddit": str(post_data.get("subreddit") or subreddit),
                "title": post_data.get("title", "") or "",
                "body": post_data.get("selftext", "") or "",
                "author": post_data.get("author", "") or "",
                "url": ("https://reddit.com" + permalink) if permalink.startswith("/") else str(post_data.get("url") or ""),
                "created_utc": created.isoformat(),
                "num_comments": int(post_data.get("num_comments") or 0),
                "reddit_score": int(post_data.get("score") or 0),
                "query": "__new_feed__",
            }
        )
    return out


def _search_rss(
    *,
    subreddit: str,
    query: str,
    headers: dict[str, str],
    timeout_seconds: int,
    search_sort: str,
    search_time_filter: str,
) -> list[dict[str, Any]]:
    """
    Fallback for when search.json is blocked/throttled.

    Uses Reddit's search RSS/Atom endpoint and parses entries.
    """
    encoded_query = urllib.parse.quote(query)
    rss_url = (
        f"https://www.reddit.com/r/{subreddit}/search.rss"
        f"?q={encoded_query}&restrict_sr=1&sort={urllib.parse.quote(search_sort)}&t={urllib.parse.quote(search_time_filter)}"
    )
    resp = _safe_get(rss_url, headers=headers, timeout_seconds=timeout_seconds)
    if resp is None:
        return []
    if resp.status_code != 200:
        logging.debug("RSS non-200 %s for %s", resp.status_code, rss_url)
        return []

    soup = BeautifulSoup(resp.text, "xml")
    entries = soup.find_all("entry")
    out: list[dict[str, Any]] = []
    for e in entries:
        title_tag = e.find("title")
        updated_tag = e.find("updated")
        title = title_tag.get_text(strip=True) if title_tag else ""
        updated = updated_tag.get_text(strip=True) if updated_tag else ""
        author = ""
        author_tag = e.find("author")
        if author_tag:
            name_tag = author_tag.find("name")
            author = name_tag.get_text(strip=True) if name_tag else ""

        link = ""
        for l in e.find_all("link"):
            if (l.get("rel") or "").lower() == "alternate" and l.get("href"):
                link = str(l.get("href"))
                break
        if not link and e.find("link") and e.find("link").get("href"):
            link = str(e.find("link").get("href"))

        # best-effort reddit_id from <id> tag
        id_tag = e.find("id")
        rid = id_tag.get_text(strip=True) if id_tag else ""
        rid = rid.split("/")[-1] if rid else ""

        created_iso = ""
        if updated:
            try:
                created_iso = datetime.fromisoformat(updated.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            except Exception:
                created_iso = datetime.now(timezone.utc).isoformat()
        else:
            created_iso = datetime.now(timezone.utc).isoformat()

        # Extract plain text from content, but keep it short.
        body = ""
        content = e.find("content")
        if content:
            body = content.get_text(" ", strip=True)

        if not link:
            continue

        out.append(
            {
                "reddit_id": rid or link,
                "subreddit": subreddit,
                "title": title,
                "body": body,
                "author": author,
                "url": link,
                "created_utc": created_iso,
                "num_comments": 0,
                "reddit_score": 0,
                "query": query,
            }
        )
    return out


def _safe_get(url: str, *, headers: dict[str, str], timeout_seconds: int) -> requests.Response | None:
    """
    requests' timeout does not reliably cap DNS resolution time on some platforms.
    Run in a worker thread and enforce a hard timeout to keep the engine responsive.
    """

    def _do() -> requests.Response:
        session = requests.Session()
        session.trust_env = False
        return session.get(url, headers=headers, timeout=timeout_seconds, allow_redirects=True)

    hard_timeout = max(1, int(timeout_seconds) + 2)
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_do)
        try:
            return fut.result(timeout=hard_timeout)
        except FutureTimeout:
            logging.debug("Hard timeout fetching %s", url)
            return None
        except Exception:
            return None
