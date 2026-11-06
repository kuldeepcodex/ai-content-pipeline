"""Reads RSS feeds and saves new articles. Already-seen URLs are skipped."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from src import db
from src.config import get_settings

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "ai-content-pipeline/0.1 (college project)"}


def _text(html: str | None) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def parse_feed(xml_text: str, source: str) -> list[dict]:
    """Turn RSS/Atom text into a list of article dicts. No network here."""
    items = []
    for e in feedparser.parse(xml_text).entries:
        url, title = e.get("link"), e.get("title")
        if not url or not title:
            continue
        if e.get("content"):
            body = e.content[0].get("value", "")
        else:
            body = e.get("summary", "")
        published = None
        if e.get("published_parsed"):
            published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        items.append({"url": url, "title": _text(title), "source": source,
                      "content": _text(body), "published_at": published})
    return items


def fetch_page_text(client: httpx.Client, url: str, max_chars: int = 6000) -> str:
    """Best effort: grab the paragraph text of the article page."""
    try:
        r = client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        return " ".join(p for p in paragraphs if len(p) > 40)[:max_chars]
    except Exception as exc:
        log.warning("page fetch failed for %s: %s", url, exc)
        return ""


def fetch_new_articles(limit: int | None = None) -> int:
    """Save new articles from every feed. Returns how many were new."""
    cfg = get_settings()
    limit = limit or cfg["limits"]["max_articles_per_run"]
    feeds = cfg["feeds"]
    per_feed = max(1, -(-limit // len(feeds)))   # spread the limit across feeds
    saved = 0
    with httpx.Client(timeout=20, follow_redirects=True, headers=HEADERS) as client:
        for feed_url in feeds:
            if saved >= limit:
                break
            try:
                resp = client.get(feed_url)
                resp.raise_for_status()
            except Exception as exc:        # one bad feed must not stop the run
                log.warning("feed failed %s: %s", feed_url, exc)
                continue
            taken = 0
            for item in parse_feed(resp.text, feed_url):
                if saved >= limit or taken >= per_feed:
                    break
                if len(item["content"]) < 600:
                    item["content"] = fetch_page_text(client, item["url"]) or item["content"]
                if db.insert_article(item["url"], item["title"], item["source"],
                                     item["content"], item["published_at"]):
                    saved += 1
                    taken += 1
    return saved
