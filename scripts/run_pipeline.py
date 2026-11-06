"""The one command that does a full run (GitHub Actions runs this too).

    python -m scripts.run_pipeline              # scrape, write drafts, publish approved ones
    python -m scripts.run_pipeline --limit 2    # only 2 new articles
    python -m scripts.run_pipeline --resume-only
"""
import argparse
import logging

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from src import alerts, db
from src.config import database_url, require_env
from src.graph.pipeline import build_graph
from src.scraper import fetch_new_articles

log = logging.getLogger("run")


def cfg(article_id: str) -> dict:
    return {"configurable": {"thread_id": article_id}}   # one saved thread per article


def run(limit: int | None = None, resume_only: bool = False) -> None:
    require_env("DATABASE_URL", "GEMINI_API_KEY")
    db.init_schema()
    run_id = db.start_run()
    found = drafts = 0
    errors: list[str] = []
    try:
        with PostgresSaver.from_conn_string(database_url()) as saver:
            saver.setup()
            graph = build_graph(saver)

            if not resume_only:
                fetch_new_articles(limit)
                for a in db.get_articles("new", limit or 20):   # includes leftovers from earlier runs
                    found += 1
                    try:
                        result = graph.invoke(
                            {"article_id": str(a["id"]), "title": a["title"],
                             "url": a["url"], "content": a["content"] or ""},
                            cfg(str(a["id"])))
                        drafts += len(result.get("drafts", []))
                        log.info("done: %s", a["title"][:70])
                    except Exception as exc:
                        db.update_article(str(a["id"]), status="failed")
                        errors.append(f"{a['title'][:50]}: {exc}")
                        log.exception("article failed")

            for article_id in db.articles_ready_to_publish():
                try:
                    graph.invoke(Command(resume=True), cfg(article_id))
                    log.info("published decisions for %s", article_id)
                except Exception as exc:
                    errors.append(f"publish {article_id}: {exc}")
                    log.exception("publish failed")
    except Exception as exc:
        db.finish_run(run_id, "failed", found, drafts, str(exc))
        alerts.notify(f"Run crashed: {type(exc).__name__}: {str(exc)[:300]}")
        raise
    db.finish_run(run_id, "failed" if errors else "ok", found, drafts, "; ".join(errors) or None)
    print(f"Run finished. Articles processed: {found}. Drafts created: {drafts}. "
          f"Errors: {len(errors)}")
    for e in errors:
        print("  -", e)
    if errors:
        alerts.notify(f"Run finished with {len(errors)} error(s). First: {errors[0][:300]}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume-only", action="store_true")
    args = ap.parse_args()
    run(args.limit, args.resume_only)
