# AI Content Pipeline

Scrapes tech news, writes posts for LinkedIn, Instagram and X with LangGraph, waits for **your approval**
in a dashboard, then records the posts (dry run). Runs on free services.

```
GitHub Actions (every 6h) -> scrape -> research -> write x3 -> critic loop -> PAUSE
                                                                              |
Vercel dashboard  <------------- you approve / edit / reject ------- Neon Postgres (all state)
                                                                              |
next scheduled run -> resumes the paused article -> records the approved posts
```

## 1. Run it on your laptop

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in the values (see below)
python -m scripts.check_setup   # expect three OK lines
python -m scripts.setup_db      # creates the tables
python -m scripts.run_pipeline --limit 2
```

`.env` values:

| Name | Where to get it |
| --- | --- |
| `GEMINI_API_KEY` | aistudio.google.com, "Get API key" |
| `GROQ_API_KEY` | console.groq.com, API keys |
| `DATABASE_URL` | Neon, Connect, **turn Connection pooling OFF**, copy the string |
| `DASHBOARD_TOKEN` | any long password you choose |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | optional, for failure alerts (section 4) |

Open the dashboard locally:

```bash
export $(grep -v '^#' .env | xargs)
uvicorn dashboard.app:app --reload     # http://localhost:8000
```

Approve some drafts, then run `python -m scripts.run_pipeline --resume-only` to record them.

## 2. Put the code on GitHub

```bash
git init && git add . && git commit -m "AI content pipeline"
```
Create an empty repo on github.com, then run the two lines GitHub shows (`git remote add origin ...` and `git push -u origin main`).
Check first that `.env` is NOT in `git status` (it is listed in `.gitignore`).

Public repos get free Actions minutes. A private repo has about 2,000 free minutes a month, which is plenty here.

## 3. Schedule it with GitHub Actions

Repo, Settings, Secrets and variables, Actions, New repository secret. Add:
`DATABASE_URL`, `GEMINI_API_KEY`, `GROQ_API_KEY` (and the two `TELEGRAM_` ones if you use alerts).

Then open the Actions tab, pick **pipeline**, press **Run workflow** to test it by hand.
After that it runs by itself every 6 hours (times are UTC).

Things to know:
- Scheduled runs can start a few minutes late, and GitHub may skip one under heavy load. The next run picks up the work.
- In a public repo, GitHub switches schedules off after 60 days with no repo activity. Press **Run workflow** or push a small commit to wake it. The dashboard shows "the schedule may have stopped" when the last run is over 12 hours old.
- GitHub emails you when a scheduled run fails.

## 4. Failure alerts on Telegram (optional, free)

1. In Telegram, message **@BotFather**, send `/newbot`, copy the token it gives you.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the number after `"chat":{"id":`.
4. Put both values in `.env` and in the GitHub secrets.

## 5. Deploy the dashboard on Vercel

1. vercel.com, sign in with GitHub, **Add New, Project**, pick your repo.
2. Set **Root Directory** to `dashboard`. Vercel detects FastAPI by itself.
3. Add environment variables `DATABASE_URL` and `DASHBOARD_TOKEN`. For Vercel you may use Neon's pooled string.
4. Deploy. Open the URL, enter your token, and you see the same drafts as locally.

The Hobby plan is free for personal, non-commercial use, which covers a college project.

## 6. Tests

```bash
pytest tests/test_scraper.py tests/test_alerts.py        # no database needed
TEST_DATABASE_URL=<a separate empty Neon database> pytest   # also runs the graph tests
```
Never point `TEST_DATABASE_URL` at your real database.

## Where things live

| Path | Job |
| --- | --- |
| `config/settings.yaml` | model names, score limits, RSS feeds, platforms |
| `src/graph/` | the LangGraph: state, prompts, nodes, pipeline |
| `src/scraper.py` | reads feeds, skips articles already seen |
| `src/db.py` | all SQL |
| `src/publisher.py` | dry-run publisher (swap in real APIs later) |
| `scripts/run_pipeline.py` | the command Actions runs |
| `dashboard/` | approval page and API (deployed on Vercel) |

## If something breaks

| Symptom | Fix |
| --- | --- |
| `check_setup` shows FAIL for Gemini | key wrong, or the model name in `settings.yaml` was retired. Models retire often. |
| Errors mentioning prepared statements | you used Neon's pooled string for the pipeline. Use the direct one. |
| `Missing in .env` | the named value is empty in `.env` or in the GitHub secrets. |
| Many `429` or quota errors | lower `max_articles_per_run` in `settings.yaml`. |
| Dashboard says 503 | `DASHBOARD_TOKEN` or `DATABASE_URL` is missing in Vercel. |
