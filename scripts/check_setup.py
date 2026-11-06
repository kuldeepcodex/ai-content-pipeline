"""Checks your keys and database before we build on them.

    python -m scripts.check_setup
"""
import os

from src.config import get_settings, require_env


def check_db() -> None:
    from src.db import get_conn
    with get_conn() as conn:
        version = conn.execute("SELECT version() AS v").fetchone()["v"]
    print("  OK  Neon:", version.split(",")[0])


def check_gemini() -> None:
    from langchain_google_genai import ChatGoogleGenerativeAI
    model = get_settings()["models"]["main"]
    reply = ChatGoogleGenerativeAI(model=model).invoke("Reply with the single word OK")
    print(f"  OK  Gemini ({model}):", str(reply.content).strip()[:40])


def check_groq() -> None:
    from langchain_groq import ChatGroq
    model = get_settings()["models"]["backup"]
    reply = ChatGroq(model=model).invoke("Reply with the single word OK")
    print(f"  OK  Groq ({model}):", str(reply.content).strip()[:40])


if __name__ == "__main__":
    checks = [("DATABASE_URL", check_db), ("GEMINI_API_KEY", check_gemini), ("GROQ_API_KEY", check_groq)]
    for env_name, fn in checks:
        try:
            require_env(env_name)
            fn()
        except Exception as exc:  # show the real reason, keep going
            print(f"  FAIL {env_name}: {type(exc).__name__}: {str(exc)[:300]}")
