"""Reads .env and config/settings.yaml. Every other file imports from here."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# LangChain's Gemini client looks for GOOGLE_API_KEY, so mirror our name to it.
if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


@lru_cache(maxsize=1)
def get_settings() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def require_env(*names: str) -> None:
    """Stop early with a clear message if a key is missing."""
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise RuntimeError(
            f"Missing in .env: {', '.join(missing)}. Copy .env.example to .env and fill it in."
        )


def database_url() -> str:
    require_env("DATABASE_URL")
    return os.environ["DATABASE_URL"]
