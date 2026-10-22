# Card Offers

A personal, single-user app that collects the card-linked offers on my credit cards in one place,
tells me which card to pay with, and emails me before offers expire.

| Part | Runs on | What it does |
|---|---|---|
| `app/` | Streamlit Community Cloud | UI: Dashboard, Search/Ask, Cards & credits, Insights, Watchlist, Alerts, Accounts. Google login (`st.login`), one allowed email. |
| `workers/` | GitHub Actions (hourly + monthly) | Gmail reader → LLM extraction → matching/dedupe → credit watchdog → alerts/emails. |
| `robot/` | My home computer | Playwright bank robot (Amex, BofA, Wells Fargo): logs in, captures the offers JSON, handles security codes through the DB. |
| DB | Supabase Postgres (free) | SQLAlchemy 2 + Alembic. Local dev uses SQLite. |

Streamlit Cloud sleeps, so nothing scheduled lives in the app. The hourly workflow also keeps
Supabase's free tier from pausing.

## Local dev (demo mode)

```sh
uv venv --python 3.12 .venv && uv pip install -r requirements-dev.txt   # + requirements-robot.txt for the robot
DEMO_MODE=true .venv/bin/streamlit run app/streamlit_app.py
.venv/bin/ruff check . && .venv/bin/pytest -q
```

`DEMO_MODE=true` seeds sample offers (Dell, Hilton, Groupon, Lyft, Under Armour, Uber Eats) into a
local `card_offers.db`. With demo mode on and no `[auth]` secrets, the login gate is skipped.

Edit `config/cards.yaml` for your cards (last digits only — never full numbers, plus the TODO
categories) and `config/settings.yaml` for grades, quiet hours, timezone and alert defaults.

## Deploy, step by step

### 1. Supabase (database)
1. Create a free project at supabase.com. **Project Settings → Database → Connection string →
   Session pooler** (port 5432, IPv4-friendly). That's `DATABASE_URL`. SSL is forced
   (`sslmode=require` is added automatically).
2. Create the tables from your machine:
   `DATABASE_URL='postgresql://…' .venv/bin/alembic upgrade head`
   (The workflows also run `alembic upgrade head` on every run.)
3. Only the app, the workers and the home robot get this URL.

### 2. Google Cloud (Gmail API + login)
1. console.cloud.google.com → new project → **APIs & Services → Library → Gmail API → Enable**.
2. **OAuth consent screen**: External, add your Gmail as a test user, add scopes
   `gmail.readonly` and `gmail.send`. Then press **Publish app → "In production"**. Unverified is
   fine for personal use (you click through a warning once). If you leave it in *Testing*,
   refresh tokens expire after 7 days and Gmail will stop syncing.
3. **Credentials → Create OAuth client ID → Desktop app** → download as `credentials.json`
   into the repo root (gitignored). Then:
   `.venv/bin/python -m workers.gmail_setup credentials.json`
   It opens a browser; approve, and it prints a token JSON. That's `GMAIL_TOKEN_JSON`.
   For more accounts, run it again per account and put the tokens in a JSON list as
   `GMAIL_TOKENS_JSON` (optional — forwarding below is simpler).
4. **Credentials → Create OAuth client ID → Web application** (for `st.login`): authorized
   redirect URI `https://<your-app>.streamlit.app/oauth2callback` (and
   `http://localhost:8501/oauth2callback` for local). Its id/secret go in the `[auth]` secrets.

Tokens live only in secrets, never in the DB.

### 3. Forward bank emails into one inbox
In **each** Gmail account: Settings → Forwarding and POP/IMAP → add the reader inbox as a
forwarding address (confirm it), then Settings → Filters → Create filter with
**From:** `americanexpress.com OR aexp.com OR bankofamerica.com OR wellsfargo.com OR discover.com OR synchronybank.com OR synchrony.com OR apple.com OR goldmansachs.com`
→ **Forward it to** the reader inbox. (Apple Card emails come from apple.com / Goldman Sachs.)
The reader only queries these senders (`config/settings.yaml: bank_senders`); other mail is never
read or sent to the LLM.

### 4. LLM provider
One `app/llm.py`, `openai` SDK for both:

| `LLM_PROVIDER` | Key | `LLM_MODEL` examples (check the provider's current catalog) |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-4.1-mini`, `gpt-5-mini` |
| `nvidia` (build.nvidia.com, `https://integrate.api.nvidia.com/v1`) | `NVIDIA_API_KEY` | `meta/llama-3.3-70b-instruct`, `nvidia/llama-3.3-nemotron-super-49b-v1` |

Each email goes to the LLM at most once (cached by Gmail message id); output is validated with
Pydantic, retried once, then marked `needs_review`.

### 5. Streamlit Community Cloud (UI)
1. share.streamlit.io → New app → this repo, branch `main`, main file `app/streamlit_app.py`,
   Python 3.12.
2. **Advanced settings → Secrets**: paste `.streamlit/secrets.toml.example` filled in —
   `DATABASE_URL`, `ALLOWED_EMAIL`, `APP_URL`, `LLM_*`, `GITHUB_TOKEN`, `GITHUB_REPO`, and the
   `[auth]` block (`redirect_uri`, `cookie_secret` = any long random string, `client_id`,
   `client_secret`, `server_metadata_url`). Set `DEMO_MODE = "false"`.
3. Only `ALLOWED_EMAIL` gets in; everyone else sees "Not authorized".

### 6. GitHub Actions (workers)
Repo → Settings → Secrets and variables → Actions → add: `DATABASE_URL`, `LLM_PROVIDER`,
`LLM_MODEL`, `OPENAI_API_KEY` or `NVIDIA_API_KEY`, `GMAIL_TOKEN_JSON`, (`GMAIL_TOKENS_JSON`),
`ALERT_EMAIL`, `ALLOWED_EMAIL`, `APP_URL`.

- `hourly.yml` (`:05` every hour + manual): Gmail → extract → match → watchdog → alerts. The
  expiry digest goes out only when it is 8 AM in America/New_York (DST-aware) and hasn't gone out
  today, so there are no UTC/DST cron bugs.
- `monthly.yml` (1st of the month): monthly recap.
- `ci.yml`: ruff + pytest on push.

**Refresh now** in the UI dispatches `hourly.yml`. Create a fine-grained personal access token
for this repo only with **Actions: Read and write**, and put it in the Streamlit secret
`GITHUB_TOKEN` (`GITHUB_REPO` = `owner/repo`). It also inserts a `refresh_requests` row that the
home robot picks up.

### 7. Home robot (Amex, BofA, Wells Fargo)
See `scripts/robot/README.md` for launchd / cron / Task Scheduler. In short:

```sh
uv pip install -r requirements-robot.txt && .venv/bin/playwright install chromium
.venv/bin/python -m robot.setup amex          # login → OS keychain, then log in once in the browser
.venv/bin/python -m robot.setup bofa          # same for BankAmeriDeals
.venv/bin/python -m robot.setup wellsfargo    # same for Wells Fargo Deals
.venv/bin/python -m robot.runner --once --bank amex --headed   # test
```

Then schedule `robot.runner --once` daily at 7 AM and `robot.runner --poll` always-on. Put
`DATABASE_URL` in the scheduler environment or `.streamlit/secrets.toml`.

- Bank passwords live only in the OS keychain (`keyring`), never in the DB, git, logs or Streamlit.
  The browser profile lives in `~/.card-offers/profiles/<bank>`.
- When the bank asks for a security code, the status turns to "needs security code", you get an
  email, and you type the code on the **Accounts** page within 10 minutes. No code → the run fails
  gracefully and the previous offers stay.
- Banks run one after another (`--once` with no `--bank` runs amex, bofa, wellsfargo), one login
  each. Use `--bank bofa` / `--bank wellsfargo` to run one.
- Selectors and the offers-JSON URL patterns at the top of `robot/amex.py`, `robot/bofa.py` and
  `robot/wellsfargo.py` need tuning against the live sites on the first run; raw payloads are
  stored in `raw_payloads` for that. If no JSON matches, the robot falls back to page text.
- No automatic enrolling: "Add to card" links to the bank's offers page.

## Troubleshooting
- **"Gmail token expired — reconnect on Accounts page"**: the consent screen was in *Testing*, or
  the token was revoked. Publish to production and re-run `python -m workers.gmail_setup`.
- **Supabase paused**: check the hourly workflow is enabled (GitHub disables scheduled workflows
  after 60 days without repo activity — re-enable in the Actions tab).
- **A bank shows "Last updated N days ago"**: it hasn't synced in 48h; check the robot logs.

## Security
Secrets only in `.streamlit/secrets.toml` (gitignored), GitHub Actions secrets and the home
keychain. Only card names and last digits are stored. Email bodies are never logged. All data
inserted into HTML is escaped.
