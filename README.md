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
cp .env.example .env
python -m scripts.check_setup
python -m scripts.setup_db
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
uvicorn dashboard.app:app --reload
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
pytest tests/test_scraper.py tests/test_alerts.py
TEST_DATABASE_URL=<a separate empty Neon database> pytest
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

## 7. Real posting to LinkedIn and X

Posting is **off by default** (dry run). It turns on only when `POST_LIVE=true`. Instagram always stays a dry run.
A post is reserved in the database before it is sent, so a retry can never post the same draft twice.
If a post fails, the draft moves to the **Failed** tab with the reason, and you get an alert.

### LinkedIn (free)
1. Go to linkedin.com/developers/apps and click **Create app**. LinkedIn asks for a Company Page. Create a simple one if you have none.
2. On the app's **Products** tab, request **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**.
3. On the **Auth** tab, add the redirect URL `http://localhost:8080/callback`, then copy the Client ID and Client Secret into `.env` as `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`.
4. Run `python -m scripts.get_linkedin_token`, sign in in the browser, and add the printed `LINKEDIN_ACCESS_TOKEN=...` line to `.env`.
5. Test: `python -m scripts.test_post linkedin --yes` makes one real public test post.

Posts go through LinkedIn's Posts API (`/rest/posts`). It needs a version header (`YYYYMM`). The code uses `202610`; LinkedIn retires old versions, so if posts fail with a version error, set `LINKEDIN_API_VERSION` to a newer month.

The token lasts about 60 days. When it expires you get an alert saying so. Run step 4 again and update the GitHub secret.

### X (paid credits)
1. Go to console.x.com, sign in, and create an app.
2. In the app's settings, set permissions to **Read and write** FIRST. Then generate the API Key and Secret and the Access Token and Secret. Tokens keep the permissions they had when they were made.
3. Open Billing and buy a small credit pack. Check the price X shows you. One source lists about $0.015 per post, and about $0.20 for a post with a link, so tweets here never include a link.
4. Put the four values in `.env` as `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`.
5. Test: `python -m scripts.test_post x --yes`.

### Turn it on
Set `POST_LIVE=true` in `.env`. To post only to LinkedIn for now, also set `POST_LIVE_PLATFORMS=linkedin`; X drafts then stay dry runs.
Then then approve a draft in the dashboard and run `python -m scripts.run_pipeline --resume-only`.
For the GitHub schedule, add the same names as repository secrets (`POST_LIVE`, `LINKEDIN_ACCESS_TOKEN`, `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`).
To stop real posting at any time, delete the `POST_LIVE` secret or set it to `false`.

## If something breaks

| Symptom | Fix |
| --- | --- |
| `check_setup` shows FAIL for Gemini | key wrong, or the model name in `settings.yaml` was retired. Models retire often. |
| Errors mentioning prepared statements | you used Neon's pooled string for the pipeline. Use the direct one. |
| `Missing in .env` | the named value is empty in `.env` or in the GitHub secrets. |
| Many `429` or quota errors | lower `max_articles_per_run` in `settings.yaml`. |
| Dashboard says 503 | `DASHBOARD_TOKEN` or `DATABASE_URL` is missing in Vercel. |
