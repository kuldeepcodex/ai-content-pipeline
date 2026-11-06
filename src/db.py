"""All database access. Plain SQL through psycopg 3."""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from src.config import database_url

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS articles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url             TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    source          TEXT,
    content         TEXT,
    published_at    TIMESTAMPTZ,
    summary         TEXT,
    relevance_score INT,
    status          TEXT NOT NULL DEFAULT 'new',   -- new | researched | rejected | drafted | failed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS drafts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id    UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    platform      TEXT NOT NULL,
    text          TEXT NOT NULL,
    hashtags      TEXT[] NOT NULL DEFAULT '{}',
    critic_score  INT,
    rewrites      INT NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending', -- pending | edited | approved | rejected | posted
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (article_id, platform)
);

CREATE TABLE IF NOT EXISTS posts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id    UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    platform    TEXT NOT NULL,
    post_ref    TEXT,
    status      TEXT NOT NULL DEFAULT 'dry_run',   -- dry_run | posted | failed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (draft_id, platform)                    -- stops double posting
);

CREATE TABLE IF NOT EXISTS runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running', -- running | ok | failed
    articles_found  INT NOT NULL DEFAULT 0,
    drafts_created  INT NOT NULL DEFAULT 0,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS drafts_status_idx ON drafts (status);
CREATE INDEX IF NOT EXISTS articles_status_idx ON articles (status);
"""


def get_conn() -> psycopg.Connection:
    """New connection that returns rows as dictionaries."""
    return psycopg.connect(database_url(), row_factory=dict_row)


def init_schema() -> list[str]:
    """Create all tables (safe to run many times). Returns the table names."""
    with get_conn() as conn:
        conn.execute(SCHEMA_SQL)
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        ).fetchall()
    return [r["table_name"] for r in rows]


def insert_article(url: str, title: str, source: str | None, content: str | None,
                   published_at=None) -> str | None:
    """Save a new article. Returns its id, or None if we have seen the URL before."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO articles (url, title, source, content, published_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (url) DO NOTHING RETURNING id",
            (url, title, source, content, published_at),
        ).fetchone()
    return str(row["id"]) if row else None


def update_article(article_id: str, **fields) -> None:
    allowed = {"summary", "relevance_score", "status"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    sets = ", ".join(f"{c} = %s" for c in cols)
    with get_conn() as conn:
        conn.execute(f"UPDATE articles SET {sets} WHERE id = %s",
                     [fields[c] for c in cols] + [article_id])


def save_draft(article_id: str, platform: str, text: str, hashtags: list[str],
               critic_score: int | None, rewrites: int) -> str:
    """Insert or replace the draft for this article and platform."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO drafts (article_id, platform, text, hashtags, critic_score, rewrites) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (article_id, platform) DO UPDATE SET text = EXCLUDED.text, "
            "hashtags = EXCLUDED.hashtags, critic_score = EXCLUDED.critic_score, "
            "rewrites = EXCLUDED.rewrites, status = 'pending' RETURNING id",
            (article_id, platform, text, hashtags, critic_score, rewrites),
        ).fetchone()
    return str(row["id"])


def list_drafts(status: str = "pending") -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT d.*, a.title AS article_title, a.url AS article_url "
            "FROM drafts d JOIN articles a ON a.id = d.article_id "
            "WHERE d.status = %s ORDER BY d.created_at DESC",
            (status,),
        ).fetchall()


def set_draft_status(draft_id: str, status: str, text: str | None = None) -> None:
    with get_conn() as conn:
        if text is None:
            conn.execute("UPDATE drafts SET status = %s WHERE id = %s", (status, draft_id))
        else:
            conn.execute("UPDATE drafts SET status = %s, text = %s WHERE id = %s",
                         (status, text, draft_id))


def start_run() -> str:
    with get_conn() as conn:
        row = conn.execute("INSERT INTO runs DEFAULT VALUES RETURNING id").fetchone()
    return str(row["id"])


def finish_run(run_id: str, status: str, articles_found: int = 0,
               drafts_created: int = 0, error: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE runs SET finished_at = now(), status = %s, articles_found = %s, "
            "drafts_created = %s, error = %s WHERE id = %s",
            (status, articles_found, drafts_created, error, run_id),
        )


def get_articles(status: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, title, url, content FROM articles WHERE status = %s "
            "ORDER BY created_at LIMIT %s", (status, limit)
        ).fetchall()


def drafts_for_article(article_id: str, status: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if status:
            return conn.execute(
                "SELECT * FROM drafts WHERE article_id = %s AND status = %s ORDER BY platform",
                (article_id, status)).fetchall()
        return conn.execute(
            "SELECT * FROM drafts WHERE article_id = %s ORDER BY platform", (article_id,)).fetchall()


def articles_ready_to_publish() -> list[str]:
    """Articles whose drafts are all decided (approved or rejected) by a human."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.id FROM articles a WHERE a.status = 'drafted' "
            "AND EXISTS (SELECT 1 FROM drafts d WHERE d.article_id = a.id) "
            "AND NOT EXISTS (SELECT 1 FROM drafts d WHERE d.article_id = a.id "
            "                AND d.status IN ('pending', 'edited'))"
        ).fetchall()
    return [str(r["id"]) for r in rows]


def record_post(draft_id: str, platform: str, post_ref: str, status: str = "dry_run") -> bool:
    """Save a post record. Returns False if this draft was already posted."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO posts (draft_id, platform, post_ref, status) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (draft_id, platform) DO NOTHING RETURNING id",
            (draft_id, platform, post_ref, status),
        ).fetchone()
    return row is not None


def claim_post(draft_id: str, platform: str) -> bool:
    """Reserve the right to post this draft BEFORE calling the platform.
    Returns False if a post record already exists, so a retry can never double post."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO posts (draft_id, platform, status) VALUES (%s, %s, 'sending') "
            "ON CONFLICT (draft_id, platform) DO NOTHING RETURNING id",
            (draft_id, platform),
        ).fetchone()
    return row is not None


def finish_post(draft_id: str, platform: str, status: str, post_ref: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE posts SET status = %s, post_ref = %s WHERE draft_id = %s AND platform = %s",
            (status, post_ref, draft_id, platform),
        )
