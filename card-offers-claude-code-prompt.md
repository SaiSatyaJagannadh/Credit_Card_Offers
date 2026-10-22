# Build prompt: "Card Offers" — my personal credit card offers app

Paste everything below into Claude Code (VS Code) in an empty folder.

---

You are building a **personal, single-user web app** that shows me every card-linked offer on my own credit cards in one place, tells me which card to pay with, and emails me before offers expire. Only I will use it. Read this whole brief, then **start by giving me a short plan and the repo layout, and wait for my OK before writing code.** Ask me if anything is ambiguous rather than guessing on anything security-related.

## 1. My cards

| Card | Issuer | Offers program | Base rewards (put in `config/cards.yaml`) |
|---|---|---|---|
| Blue Cash Everyday ••92006 | American Express | Amex Offers | 3% U.S. supermarkets, U.S. online retail, U.S. gas (each up to $6k/yr, then 1%); 1% else |
| Customized Cash Rewards | Bank of America | BankAmeriDeals | 3% choice category + 2% grocery/wholesale clubs (combined $2,500/quarter cap); 1% else |
| Visa Signature | Wells Fargo | Wells Fargo Deals | 1x else; other categories TODO (I'll confirm) |
| Discover it | Discover | none | 5% rotating quarterly (must activate); 1% else |
| Verizon Visa | Synchrony | none | 1% else; other categories TODO |
| Apple Card | Apple | none | 2% with Apple Pay; 1% physical card |

Store only card names and last digits. Never store full card numbers.

## 2. Architecture (non-negotiable)

Streamlit Community Cloud **sleeps** when unused, so nothing scheduled may live inside the Streamlit app.

- **UI:** Streamlit app deployed on Streamlit Community Cloud. Multipage via `st.navigation`. Login with `st.login` (Google OIDC), and only allow the email in `ALLOWED_EMAIL`; everyone else sees "Not authorized".
- **Database:** Supabase Postgres (free tier) through SQLAlchemy 2.x + Alembic migrations, using `DATABASE_URL`. Local dev may use SQLite through the same models.
- **Background workers:** a `workers/` package run by **GitHub Actions** (cron + `workflow_dispatch`):
  - `hourly.yml` runs every hour: Gmail reader → extraction → matching → alerts check. It sends the daily expiry email only when the local time (America/New_York, DST-aware) is 8 AM and no digest has gone out today (idempotency table). This avoids UTC/DST cron bugs.
  - `monthly.yml` runs on the 1st: monthly recap email.
  - Keep each run under ~2 minutes (free-minutes budget). The hourly runs also keep Supabase's free tier from pausing.
- **Bank robot (Phase 3, Amex first):** a `robot/` package that runs **on my home computer, not in the cloud** (banks block datacenter IPs). It uses Playwright with a persistent browser profile. It runs daily at 7 AM via OS scheduler (launchd/cron/Task Scheduler) and also polls a `refresh_requests` table every 2 minutes. It writes results to the same Supabase DB.
- **"Refresh now" button:** calls the GitHub API to `workflow_dispatch` the hourly workflow (Gmail), and inserts a `refresh_requests` row (robot). The UI shows live per-source status from `sync_runs`, e.g. "Amex: syncing… / synced 7:02 AM / needs security code".
- **AI provider switch:** one `app/llm.py` using the `openai` Python SDK for both providers:
  - `LLM_PROVIDER=openai` → default base URL, `OPENAI_API_KEY`
  - `LLM_PROVIDER=nvidia` → `base_url="https://integrate.api.nvidia.com/v1"`, `NVIDIA_API_KEY`
  - `LLM_MODEL` comes from config (no hardcoded model names; README gives current examples for each provider).
  - Structured output: request JSON, validate with Pydantic, retry once on validation failure, then mark the email `needs_review`. Cache results by Gmail `message_id` so no email is sent to the LLM twice.

## 3. Data sources

### 3a. Gmail reader (Phase 1)
- I have several Gmail accounts. README must explain setting up **forwarding filters** in each (from americanexpress.com, bankofamerica.com, wellsfargo.com, discover.com, synchronybank.com, Apple Card) into **one** inbox, which the app reads. Also support an optional list of multiple OAuth tokens in config.
- Gmail API OAuth, scopes `gmail.readonly` + `gmail.send` (to email me). README must say to set the OAuth consent screen to **"In production"** (unverified is fine for personal use); otherwise refresh tokens expire after 7 days. Tokens live in secrets, never in the DB.
- Query only bank senders and new messages since the last `history_id`. Pre-filter by sender, then have the LLM classify each email as one of: `offer_new`, `offer_reminder`, `transaction_alert`, `credit_posted`, `statement`, `other`.
- Extract per type into Pydantic models:
  - **Offer:** merchant, offer_text, type (pct|fixed|points), pct, fixed_amount, min_spend, max_credit, expires_on, card_last_digits, channel (online|in_store|both), exclusions (e.g. third-party/PayPal/Apple Pay), source_message_id
  - **Transaction:** merchant_raw, amount, date, card_last_digits
  - **Credit:** merchant, amount, date, card_last_digits, offer reference if present
- Strip email HTML to text and truncate before sending to the LLM. Never send full emails of non-bank senders.

### 3b. Bank robot (Phase 3)
- Start with Amex only. Later add BofA and Wells Fargo as separate modules sharing one `BaseBankRobot` interface: `login()`, `fetch_offers()`, `needs_mfa()`, `submit_mfa(code)`.
- Credentials come from the OS keychain via `keyring`, entered once with a CLI (`python -m robot.setup amex`). Never in the DB, git, logs or Streamlit.
- Prefer capturing the JSON the offers page loads (Playwright response interception) over DOM scraping. Store the raw payload in `raw_payloads` for debugging. Use one login per bank per run, human-paced, no parallel sessions.
- MFA flow: robot detects a code prompt → sets the bank's status to `needs_code` → emails me → waits up to 10 minutes polling `mfa_codes` (I type it on the Accounts page; codes expire after 10 min and are deleted after use) → continues. If no code arrives, the run fails gracefully and keeps the old data.
- No automatic offer enrolling in v1. "Add to card" deep-links to the bank's offers page.
- Mark stale data: if a bank hasn't synced in more than 48h, show "Last updated N days ago".

## 4. Matching and scoring

- **Merchant normalization:** an alias table + `rapidfuzz` (threshold ~90), with an LLM fallback that maps a raw merchant to an existing canonical merchant or "new". Persist learned aliases.
- **Dedupe:** the same offer from email and from robot = one row (key: issuer + card + merchant_norm + expires_on + value).
- **Effective value for a purchase:** `offer_value(amount)` (respecting min_spend, pct, cap) + `base_rate(card, category) × amount`, with caps from `cards.yaml` (track cap usage from transactions).
- **Grades** (configurable): A ≥ $40 max value, B ≥ $15, C otherwise.
- **"New"** = first seen since the previous sync. **"You shop here"** = merchant appears in my transactions in the last 180 days.
- **Amex single-card rule:** an Amex offer can be enrolled on only one card. When an offer appears on several Amex cards, recommend the card with the best base rate for that merchant.

## 5. Features and acceptance criteria

**Dashboard**
- Header: "Last synced …", search box ("Search or ask: best card for $40 at Uber?"), **Refresh now** with per-source progress.
- KPI tiles: Value on your cards ($ sum of max values), Not added yet ($ + count), Expiring in 7 days (count + names), Saved this year (credits posted).
- **To-do** cards with buttons: add high-value unadded offers, enter BofA/any MFA code, activate Discover 5% at quarter start, review BofA 3% category monthly, use an inactive card (no purchase in 90 days). Items can be marked done.
- **Top offers:** filters All / For you / Not added / Added. Sort: highest value / expiring first / newest. Each row shows merchant initial, grade badge, New badge, "You shop here" badge, offer text, card chip, expiry chip (amber if ≤7 days), "up to $X", Added pill or "Add to card" link.
- **Use these before they expire** list. Right column: Connected accounts with status pills and an inline MFA code box, Credits posted, Gmail reader status.

**Search / Ask (works well on a phone)**
- Merchant + amount → best card first, with breakdown ("Offer 20% = $8.00 (cap $10) + base 1% = $0.40"), offer status and expiry, exclusion warning, then my other cards ranked.
- Free-text questions go to the LLM, answering **only** from rows I pass it (offers, cards.yaml rules, transactions). If the data doesn't cover it, say so. Never invent offers.
- "I'm at…" box (Streamlit has no background location): typing a store name shows offers + best card there.

**Cards & credits**
- Best card per category (groceries, online, gas, BofA choice category, Discover rotating, everything else).
- Perk/cap trackers with progress bars (Amex $6k category caps, BofA $2,500 quarterly cap, any monthly credits I add in cards.yaml).
- "Saved from offers" monthly bar chart (Altair) and a cards table (bonus categories, everything else, offers program).

**Insights**
- **Missed-savings report:** for each transaction, compare what I earned vs the best card+offer available on that date. Show monthly total missed and the top 5 misses ("Lyft on Discover: missed $4.50, Wells Fargo had 10% back").
- **Credit watchdog:** when a transaction qualifies for an added offer, create an expected credit (amount, due date = purchase + `CREDIT_DUE_DAYS`, default 21). Statuses: waiting, posted (matched to a credit email), overdue (alert me, with purchase date/amount/offer text ready to send the bank).
- **Spend progress** on min-spend offers ("Dell: $0 of $300").

**Watchlist**
- Add merchants (e.g. Costco, Apple, Delta). Alert when any card gets a matching offer.

**Alerts page** (toggles stored in `settings`)
- New high-value offer (min $ threshold: 5/10/20/50).
- **Offer expires in 3 days:** email to my Gmail at 8 AM, 3 days before, and again 1 day before if still unused. Bundle all expiring offers into one email.
- Bank needs a security code (immediate).
- Credit posted. Credit overdue (watchdog).
- Rotating category reminder (Discover quarterly, BofA monthly).
- Watchlist match. Weekly summary (Sunday 9 AM, off by default). Monthly recap (1st of month).
- Channels: email on. Quiet hours 10 PM–7 AM (hold, send at 7).
- Every sent alert is logged in `alerts_sent` with a dedupe key so nothing is sent twice.

**Emails** (HTML, inline CSS, also render a plain-text part)
- 3-day expiry email layout: subject "Groupon offer expires in 3 days: $20 back unused". A green hero block with expiry date, offer, card and added status. Buttons: "Add on <bank>" (deep link), "Add to my calendar" (Google Calendar template link). How much to spend for the full credit. "Also expiring soon" list. "Credit to watch" block. Footer links to the dashboard and the alerts page.
- Monthly recap: offers used, credits posted, missed savings, top new offers.

## 6. Design (match it closely with custom CSS in `app/ui/theme.py`)

- Fonts: Manrope (UI), JetBrains Mono (money figures) via Google Fonts.
- Colors: page `#F7F8FA`, cards `#FFFFFF` with `1px #E5E7EB` border and 14px radius, text `#111827`, muted `#4B5563`, accent `#0B6E4F`.
- Pills: green `#E7F5EE`/`#0B5E43`, amber `#FFF4E0`/`#8A4B00`, blue `#E8F0FE`/`#1E4FA3`, purple `#F1ECFE`/`#5B21B6`, gray `#F3F4F6`/`#4B5563`.
- Build offer rows, KPI tiles, pills and to-do cards as reusable HTML components (`st.html`/`st.markdown(unsafe_allow_html=True)`). **Escape all data before inserting it into HTML** (merchant names come from emails).
- Mobile: layouts must stack at phone width; touch targets ≥ 44px; no horizontal scroll except inside wide tables.
- Text contrast ≥ 4.5:1. No emoji as icons.
- Pages: Dashboard, Search, Cards & credits, Insights, Watchlist, Alerts, Accounts (sync status, MFA code entry, Gmail connection info).

## 7. Data model (SQLAlchemy; adjust if you have a better shape, but explain why)

`cards`, `offers` (with `first_seen_at`, `last_seen_at`, `source` email|robot, `enrolled`, `status` active|expired|used), `merchants`, `merchant_aliases`, `transactions`, `credits`, `expected_credits`, `sync_runs` (source, started_at, finished_at, status, message), `refresh_requests`, `mfa_codes`, `raw_payloads`, `emails_processed` (message_id, type, status), `alerts_sent`, `watchlist`, `todos_done`, `settings`.

## 8. Security rules

- Secrets only in `.streamlit/secrets.toml` (gitignored), GitHub Actions secrets, and the home machine's keychain. Add `.env.example` and `secrets.toml.example`.
- No bank passwords anywhere except the home keychain. No full card numbers. No email bodies in logs.
- Use Supabase connection over SSL. Only the app and workers have the DB URL.
- Add a "demo mode" (`DEMO_MODE=true`) that seeds sample offers so the UI can be developed without real data. Seed: Dell $60/$300 Amex exp Oct 31; Hilton $50/$250 Amex; Groupon 15% up to $20 BofA; Lyft 10% up to $15 Wells Fargo; Under Armour 20% up to $10 Amex ••92006 exp Nov 8 (added); Uber Eats $5 on $25 BofA.

## 9. Repo layout (suggested)

```
app/            streamlit_app.py, pages/, ui/theme.py, ui/components.py, llm.py, ranking.py, db.py
workers/        gmail_reader.py, extract.py, match.py, alerts.py, emails/ (templates), run_hourly.py, run_monthly.py
robot/          base.py, amex.py, setup.py, runner.py
config/         cards.yaml, settings.yaml
migrations/     alembic
tests/          fixtures/ (sanitized sample bank emails), test_extract.py, test_ranking.py, test_alerts.py
.github/workflows/  hourly.yml, monthly.yml
README.md
```

## 10. Build phases (commit after each, run tests, show me the result before moving on)

1. **Skeleton + demo mode:** DB models + migrations, cards.yaml, theme, all pages with seeded data, ranking logic + tests, `st.login` gate.
2. **Gmail pipeline:** OAuth setup script, reader, LLM extraction with the provider switch, matching/dedupe, transactions and credits, tests with fixture emails (no live API calls in tests).
3. **Alerts + emails:** 3-day/1-day expiry emails, other alerts, quiet hours, dedupe, GitHub Actions workflows, Refresh now via `workflow_dispatch`.
4. **Insights:** missed savings, credit watchdog, spend progress, watchlist, monthly recap.
5. **Amex robot on my home machine:** keyring setup, Playwright persistent profile, JSON capture, MFA flow via DB, refresh-request polling, scheduler setup per OS. Then BofA and Wells Fargo.
6. **Deploy:** step-by-step README for Google Cloud (Gmail API, OAuth in production), Supabase, Streamlit Community Cloud (secrets, `st.login` config), GitHub Actions secrets, and the home robot.

Ground rules: Python 3.12, type hints, `ruff` + `pytest`. Small modules. Clear error messages in the UI (e.g. "Gmail token expired — reconnect on Accounts page"). Don't add features not listed here without asking.
