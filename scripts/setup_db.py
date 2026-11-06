"""Run once: creates all tables in your Neon database.

    python -m scripts.setup_db
"""
from src.db import init_schema

if __name__ == "__main__":
    tables = init_schema()
    print("Database ready. Tables:", ", ".join(tables))
