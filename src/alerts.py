"""Failure alerts. Telegram if configured, always logged. Never raises."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)


def notify(message: str) -> bool:
    """Send an alert. Returns True only if a Telegram message was delivered."""
    log.warning("ALERT: %s", message)
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        resp = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": f"[content pipeline] {message}"[:3500]},
                          timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:
        # Do not log str(exc): httpx puts the full URL, including the bot token, in it.
        log.warning("Telegram alert failed (%s)", type(exc).__name__)
        return False
