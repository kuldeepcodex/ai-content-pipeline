"""Sends ONE real test post to check your credentials, without running the pipeline.

    python -m scripts.test_post linkedin --yes
    python -m scripts.test_post x --yes
"""
import argparse
import datetime

from src import publisher
from src.publisher import PostError

ap = argparse.ArgumentParser()
ap.add_argument("platform", choices=["linkedin", "x"])
ap.add_argument("--yes", action="store_true", help="confirm that you want a REAL public post")
args = ap.parse_args()

if not args.yes:
    raise SystemExit("This makes a real public post. Add --yes to confirm.")

text = f"Test post from my college project ({datetime.datetime.now():%d %b %H:%M}). Please ignore."
try:
    ref = publisher.post_linkedin(publisher.escape_linkedin(text)) if args.platform == "linkedin" else publisher.post_x(text)
    print("Posted. Reference:", ref, "\nDelete the test post from your account if you do not want it.")
except PostError as exc:
    raise SystemExit(f"FAILED: {exc}")
