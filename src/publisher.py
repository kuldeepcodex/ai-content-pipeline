"""Dry-run publisher: records what WOULD be posted. Real APIs can be added later."""
from __future__ import annotations

from src import db


def publish_draft(draft: dict) -> bool:
    """Returns True if recorded, False if this draft was already recorded."""
    draft_id = str(draft["id"])
    return db.record_post(draft_id, draft["platform"], f"dry-run-{draft_id[:8]}", "dry_run")
