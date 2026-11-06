"""Publishes approved drafts. Dry run by default; real posting needs POST_LIVE=true.

LinkedIn: free, uses a 60-day access token.  X: needs paid API credits.
Instagram is always a dry run (it needs a business account and an image).
"""
from __future__ import annotations

import logging
import os

import httpx
import requests
from requests_oauthlib import OAuth1

from src import alerts, db

log = logging.getLogger(__name__)

LINKEDIN_MAX = 3000
X_MAX = 280
LINKEDIN_API = "https://api.linkedin.com"
LINKEDIN_VERSION = "202610"   # YYYYMM. LinkedIn retires old versions; override with LINKEDIN_API_VERSION
X_API = "https://api.x.com/2/tweets"


class PostError(Exception):
    """A readable reason a post failed."""


def live_enabled() -> bool:
    return os.getenv("POST_LIVE", "").strip().lower() == "true"


def live_platforms() -> set[str]:
    """Platforms that really post. Set POST_LIVE_PLATFORMS=linkedin to post only there."""
    raw = os.getenv("POST_LIVE_PLATFORMS", "linkedin,twitter")
    return {p.strip().lower() for p in raw.split(",") if p.strip()} & {"linkedin", "twitter"}


def _tags(hashtags: list[str]) -> str:
    return " ".join("#" + t for t in hashtags)


_LITTLE_TEXT_RESERVED = set("\\|{}@[]()<>#*_~")


def escape_linkedin(text: str) -> str:
    """LinkedIn's post text format treats these characters as markup. Unescaped
    parentheses and brackets can silently cut the post short, so escape them all."""
    return "".join("\\" + ch if ch in _LITTLE_TEXT_RESERVED else ch for ch in text)


def build_linkedin_text(draft: dict, article_url: str | None) -> str:
    text = draft["text"].strip()
    tags = _tags(draft["hashtags"])
    if tags:
        text += "\n\n" + tags
    if article_url:                       # links are free on LinkedIn
        text += f"\n\nSource: {article_url}"
    out = escape_linkedin(text)[:LINKEDIN_MAX]
    trailing = len(out) - len(out.rstrip("\\"))
    if trailing % 2:                      # never end on half of an escape pair
        out = out[:-1]
    return out


def build_tweet(draft: dict) -> str:
    tweet = draft["text"].strip()
    tags = _tags(draft["hashtags"])
    if tags:
        tweet += " " + tags
    if len(tweet) > X_MAX:
        raise PostError(f"Tweet is {len(tweet)} characters, the limit is {X_MAX}")
    return tweet                          # no link on purpose: link posts cost far more on X


def _need(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise PostError(f"Missing credentials: {', '.join(missing)}")


def post_linkedin(text: str) -> str:
    """Posts with LinkedIn's Posts API (POST /rest/posts). `text` must already be escaped."""
    _need("LINKEDIN_ACCESS_TOKEN")
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
    version = os.getenv("LINKEDIN_API_VERSION", LINKEDIN_VERSION)
    headers = {"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0",
               "Linkedin-Version": version, "Content-Type": "application/json"}
    try:
        person = os.getenv("LINKEDIN_PERSON_ID")
        if not person:
            r = httpx.get(f"{LINKEDIN_API}/v2/userinfo", headers={"Authorization": f"Bearer {token}"},
                          timeout=20)
            _check_linkedin(r)
            person = r.json()["sub"]
        body = {
            "author": f"urn:li:person:{person}",
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = httpx.post(f"{LINKEDIN_API}/rest/posts", headers=headers, json=body, timeout=20)
        _check_linkedin(r)
    except httpx.HTTPError as exc:
        raise PostError(f"LinkedIn network error ({type(exc).__name__})") from None
    return r.headers.get("x-restli-id", "unknown")


def _check_linkedin(r: httpx.Response) -> None:
    if r.status_code == 401:
        raise PostError("LinkedIn token expired or invalid. Make a new one with "
                        "`python -m scripts.get_linkedin_token` and update the secret.")
    if r.status_code >= 400:
        hint = " (check LINKEDIN_API_VERSION, LinkedIn may have retired that version)" \
            if r.status_code in (400, 404, 426) and "ersion" in r.text else ""
        raise PostError(f"LinkedIn error {r.status_code}: {r.text[:200]}{hint}")


def post_x(text: str) -> str:
    _need("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
    auth = OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                  os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"])
    try:
        r = requests.post(X_API, json={"text": text}, auth=auth, timeout=20)
    except requests.RequestException as exc:
        raise PostError(f"X network error ({type(exc).__name__})") from None
    if r.status_code >= 400:
        hint = " (check that the app has Read and write permission and that you have credits)" \
            if r.status_code in (401, 402, 403) else ""
        raise PostError(f"X error {r.status_code}: {r.text[:200]}{hint}")
    return r.json()["data"]["id"]


def publish_draft(draft: dict, article_url: str | None = None) -> dict:
    """Returns {"status": posted | dry_run | failed | skipped, "ref": ..., "error": ...}."""
    platform, draft_id = draft["platform"], str(draft["id"])
    live = live_enabled() and platform in live_platforms()

    if not db.claim_post(draft_id, platform):
        return {"status": "skipped", "ref": None, "error": None}

    try:
        if live and platform == "linkedin":
            ref = post_linkedin(build_linkedin_text(draft, article_url))
        elif live and platform == "twitter":
            ref = post_x(build_tweet(draft))
        else:
            ref = f"dry-run-{draft_id[:8]}"
        status = "posted" if live else "dry_run"
    except PostError as exc:
        db.finish_post(draft_id, platform, "failed", str(exc)[:300])
        alerts.notify(f"{platform} post failed: {exc}")
        return {"status": "failed", "ref": None, "error": str(exc)}

    db.finish_post(draft_id, platform, status, ref)
    return {"status": status, "ref": ref, "error": None}
