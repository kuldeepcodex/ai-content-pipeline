"""Approval dashboard API. Small on purpose: it only reads and updates drafts in Neon.

Run locally from the project root:
    uvicorn dashboard.app:app --reload
Deploy: set Vercel's Root Directory to `dashboard`.
"""
from __future__ import annotations

import os
import secrets
import uuid
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

app = FastAPI(title="Content approval dashboard")
PAGE = Path(__file__).with_name("index.html")
TWITTER_MAX = 240
REVIEW = ("pending", "edited")


def conn() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(503, "DATABASE_URL is not set on the server")
    # prepare_threshold=None keeps this safe behind Neon's pooled connection
    return psycopg.connect(url, row_factory=dict_row, prepare_threshold=None)


def require_auth(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("DASHBOARD_TOKEN")
    if not token:   # fail closed: no token configured means nobody gets in
        raise HTTPException(503, "DASHBOARD_TOKEN is not set on the server")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(401, "Wrong token")


class EditBody(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/drafts", dependencies=[Depends(require_auth)])
def list_drafts(status: str = "review") -> list[dict]:
    statuses = REVIEW if status == "review" else (status,)
    if status not in ("review", "approved", "rejected", "posted"):
        raise HTTPException(422, "status must be review, approved, rejected or posted")
    with conn() as c:
        return c.execute(
            "SELECT d.id, d.platform, d.text, d.hashtags, d.critic_score, d.rewrites, d.status, "
            "d.created_at, a.title AS article_title, a.url AS article_url "
            "FROM drafts d JOIN articles a ON a.id = d.article_id "
            "WHERE d.status = ANY(%s) ORDER BY d.created_at DESC, d.platform",
            (list(statuses),),
        ).fetchall()


@app.get("/api/stats", dependencies=[Depends(require_auth)])
def stats() -> dict:
    with conn() as c:
        counts = c.execute("SELECT status, count(*) AS n FROM drafts GROUP BY status").fetchall()
        last = c.execute(
            "SELECT started_at, finished_at, status, articles_found, drafts_created, error "
            "FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    by_status = {r["status"]: r["n"] for r in counts}
    return {"drafts": by_status, "needs_review": by_status.get("pending", 0) + by_status.get("edited", 0),
            "last_run": last}


@app.patch("/api/drafts/{draft_id}", dependencies=[Depends(require_auth)])
def edit_draft(draft_id: uuid.UUID, body: EditBody) -> dict:
    text = body.text.strip()
    with conn() as c:
        row = c.execute("SELECT platform, hashtags, status FROM drafts WHERE id = %s",
                        (draft_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Draft not found")
        if row["status"] not in REVIEW:
            raise HTTPException(409, f"Draft is already {row['status']}")
        if row["platform"] == "twitter":
            length = len(text) + sum(len(t) + 2 for t in row["hashtags"])
            if length > TWITTER_MAX:
                raise HTTPException(422, f"Too long for X: {length}/{TWITTER_MAX} characters "
                                         "including hashtags")
        c.execute("UPDATE drafts SET text = %s, status = 'edited' WHERE id = %s", (text, draft_id))
    return {"id": str(draft_id), "status": "edited"}


def _decide(draft_id: uuid.UUID, new_status: str) -> dict:
    with conn() as c:
        row = c.execute(
            "UPDATE drafts SET status = %s WHERE id = %s AND status = ANY(%s) RETURNING id",
            (new_status, draft_id, list(REVIEW))).fetchone()
    if not row:
        raise HTTPException(409, "Draft not found or already decided")
    return {"id": str(draft_id), "status": new_status}


@app.post("/api/drafts/{draft_id}/approve", dependencies=[Depends(require_auth)])
def approve(draft_id: uuid.UUID) -> dict:
    return _decide(draft_id, "approved")


@app.post("/api/drafts/{draft_id}/reject", dependencies=[Depends(require_auth)])
def reject(draft_id: uuid.UUID) -> dict:
    return _decide(draft_id, "rejected")
