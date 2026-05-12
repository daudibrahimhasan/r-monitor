from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Database:
    db_path: Path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=MEMORY;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
        except Exception:
            pass
        return conn

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reddit_id TEXT UNIQUE,
                    subreddit TEXT,
                    title TEXT,
                    body TEXT,
                    author TEXT,
                    url TEXT UNIQUE,
                    created_utc TEXT,
                    found_at TEXT,
                    research_topic TEXT,
                    score INTEGER,
                    status TEXT
                );

                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER,
                    contact_type TEXT,
                    contact_value TEXT,
                    source_url TEXT,
                    safe_to_email INTEGER,
                    reason TEXT,
                    created_at TEXT,
                    FOREIGN KEY(post_id) REFERENCES posts(id)
                );

                CREATE TABLE IF NOT EXISTS outreach (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER,
                    contact_id INTEGER,
                    channel TEXT,
                    subject TEXT,
                    body TEXT,
                    status TEXT,
                    sent_at TEXT,
                    followup_due_at TEXT,
                    followup_sent INTEGER DEFAULT 0,
                    replied INTEGER DEFAULT 0,
                    opted_out INTEGER DEFAULT 0,
                    FOREIGN KEY(post_id) REFERENCES posts(id),
                    FOREIGN KEY(contact_id) REFERENCES contacts(id)
                );

                CREATE TABLE IF NOT EXISTS suppression (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_value TEXT UNIQUE,
                    reason TEXT,
                    created_at TEXT
                );
                """
            )
            self._ensure_column(conn, "posts", "research_topic", "TEXT")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def post_exists(self, *, url: str, reddit_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM posts WHERE url = ? OR reddit_id = ? LIMIT 1",
                (url, reddit_id),
            ).fetchone()
            return row is not None

    def save_post(self, post: dict[str, Any], *, status: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO posts
                (reddit_id, subreddit, title, body, author, url, created_utc, found_at, research_topic, score, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post.get("reddit_id"),
                    post.get("subreddit"),
                    post.get("title", ""),
                    post.get("body", ""),
                    post.get("author", ""),
                    post.get("url"),
                    post.get("created_utc"),
                    now,
                    post.get("research_topic", ""),
                    int(post.get("score", 0)),
                    status,
                ),
            )
            return int(cur.lastrowid)

    def save_contact(self, post_id: int, contact: dict[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO contacts
                (post_id, contact_type, contact_value, source_url, safe_to_email, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    contact.get("type"),
                    contact.get("value"),
                    contact.get("source_url"),
                    1 if contact.get("safe_to_email") else 0,
                    contact.get("reason", ""),
                    now,
                ),
            )
            return int(cur.lastrowid)

    def save_outreach(
        self,
        *,
        post_id: int,
        contact_id: int | None,
        channel: str,
        subject: str,
        body: str,
        status: str,
        sent_at: datetime | None,
        followup_due_at: datetime | None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO outreach
                (post_id, contact_id, channel, subject, body, status, sent_at, followup_due_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    contact_id,
                    channel,
                    subject,
                    body,
                    status,
                    sent_at.isoformat() if sent_at else None,
                    followup_due_at.isoformat() if followup_due_at else None,
                ),
            )
            return int(cur.lastrowid)

    def is_suppressed(self, contact_value: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM suppression WHERE contact_value = ? LIMIT 1",
                (contact_value,),
            ).fetchone()
            return row is not None

    def sent_to_contact_recently(self, contact_value: str, *, days: int) -> bool:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM outreach o
                JOIN contacts c ON c.id = o.contact_id
                WHERE c.contact_value = ?
                  AND o.status = 'sent'
                  AND o.sent_at IS NOT NULL
                  AND o.sent_at >= ?
                LIMIT 1
                """,
                (contact_value, since),
            ).fetchone()
            return row is not None

    def count_sent_today(self, now_utc: datetime) -> int:
        start = now_utc.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM outreach
                WHERE status = 'sent'
                  AND sent_at IS NOT NULL
                  AND sent_at >= ?
                """,
                (start.isoformat(),),
            ).fetchone()
            return int(row["c"]) if row else 0

    def compute_followup_due_at(self, cfg: dict[str, Any]) -> datetime:
        hours = int(cfg.get("automation", {}).get("followup_after_hours", 48))
        return datetime.now(timezone.utc) + timedelta(hours=hours)

    def get_followup_candidates(self, *, now_utc: datetime, min_age_hours: int) -> list[dict[str, Any]]:
        cutoff = (now_utc - timedelta(hours=min_age_hours)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    o.id AS outreach_id,
                    o.subject,
                    c.contact_value AS email,
                    o.sent_at
                FROM outreach o
                JOIN contacts c ON c.id = o.contact_id
                WHERE o.status = 'sent'
                  AND o.followup_sent = 0
                  AND o.replied = 0
                  AND o.opted_out = 0
                  AND o.sent_at IS NOT NULL
                  AND o.sent_at <= ?
                  AND c.contact_type = 'email'
                  AND c.safe_to_email = 1
                """,
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_followup_sent(self, outreach_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE outreach SET followup_sent = 1 WHERE id = ?",
                (outreach_id,),
            )

    def get_today_leads(self, *, now_utc: datetime) -> list[dict[str, Any]]:
        start = now_utc.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.id,
                    p.subreddit,
                    p.title,
                    p.url,
                    p.created_utc,
                    p.author,
                    p.research_topic,
                    p.score,
                    p.status,
                    p.found_at,
                    c.contact_type,
                    c.contact_value,
                    c.safe_to_email,
                    o.status AS outreach_status
                FROM posts p
                LEFT JOIN contacts c ON c.post_id = p.id
                LEFT JOIN outreach o ON o.post_id = p.id
                WHERE p.found_at >= ?
                  AND p.status IN ('lead')
                ORDER BY p.created_utc DESC, p.score DESC
                """,
                (start,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_leads(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.id,
                    p.subreddit,
                    p.title,
                    p.url,
                    p.created_utc,
                    p.author,
                    p.research_topic,
                    p.score,
                    p.status,
                    p.found_at,
                    c.contact_type,
                    c.contact_value,
                    c.safe_to_email,
                    o.status AS outreach_status
                FROM posts p
                LEFT JOIN contacts c ON c.post_id = p.id
                LEFT JOIN outreach o ON o.post_id = p.id
                WHERE p.status IN ('lead', 'research_candidate')
                ORDER BY p.created_utc DESC, p.score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_drafts(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    o.id AS outreach_id,
                    p.id AS post_id,
                    p.subreddit,
                    p.title,
                    p.url,
                    p.created_utc,
                    p.author,
                    p.score,
                    p.status AS lead_status,
                    c.contact_type,
                    c.contact_value,
                    c.safe_to_email,
                    o.channel,
                    o.subject,
                    o.body,
                    o.status AS outreach_status,
                    o.sent_at,
                    o.followup_due_at,
                    o.followup_sent,
                    o.replied,
                    o.opted_out
                FROM outreach o
                JOIN posts p ON p.id = o.post_id
                LEFT JOIN contacts c ON c.id = o.contact_id
                ORDER BY p.created_utc DESC, p.score DESC, o.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lead_counts_by_subreddit(self, *, now_utc: datetime) -> dict[str, dict[str, int]]:
        start = now_utc.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    subreddit,
                    SUM(CASE WHEN found_at >= ? THEN 1 ELSE 0 END) AS today_count,
                    COUNT(*) AS total_count
                FROM posts
                WHERE status IN ('lead', 'research_candidate')
                GROUP BY subreddit
                """,
                (start,),
            ).fetchall()
            return {
                str(r["subreddit"]): {
                    "today": int(r["today_count"] or 0),
                    "total": int(r["total_count"] or 0),
                }
                for r in rows
            }

    def iter_review_queue(self, *, limit: int = 200) -> Iterable[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    o.id AS outreach_id,
                    p.subreddit,
                    p.title,
                    p.url,
                    p.score,
                    o.status,
                    o.subject,
                    o.body
                FROM outreach o
                JOIN posts p ON p.id = o.post_id
                WHERE o.status IN ('queued_for_review', 'no_safe_contact_found', 'reddit_reply_or_dm_review')
                ORDER BY p.score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for r in rows:
                yield dict(r)

    def get_research_leads(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.id,
                    p.subreddit,
                    p.title,
                    p.body,
                    p.author,
                    p.url,
                    p.created_utc,
                    p.research_topic,
                    p.score,
                    p.status,
                    o.subject AS outreach_subject,
                    o.body AS outreach_body
                FROM posts p
                LEFT JOIN outreach o ON o.post_id = p.id
                WHERE p.status = 'research_candidate'
                ORDER BY p.created_utc DESC, p.score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
