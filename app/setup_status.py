"""First-run checklist: each step's done-ness comes from real state (secrets, sync_runs, DB)."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import cards_config, secret
from app.db import Offer, database_url, latest_sync, utcnow

BANKS = {"amex": "Amex", "bofa": "Bank of America", "wellsfargo": "Wells Fargo"}


@dataclass
class Step:
    key: str
    title: str
    done: bool
    status: str  # one short line of what the app sees right now
    how: str  # what to do, in plain words
    page: str = ""  # in-app page that fixes it
    command: str = ""  # terminal command on the Mac, if any


def steps(s: Session, logged_in: bool) -> list[Step]:
    url = database_url()
    online = url.startswith("postgresql")
    gmail = latest_sync(s, "gmail")
    gmail_ok = bool(gmail and gmail.status == "ok"
                    and gmail.started_at > utcnow() - timedelta(hours=3))
    llm_key = secret("OPENAI_API_KEY") or secret("NVIDIA_API_KEY")
    digits = [c for c in cards_config() if c.get("last_digits")]
    offers = s.scalar(select(func.count(Offer.id))) or 0
    out = [
        Step("db", "Online database", online,
             "Connected to Supabase" if online else "Using a local test database",
             "Create a free Supabase project and put its Session pooler URL in DATABASE_URL."),
        Step("login", "Private login", logged_in,
             "Only your Google account can open this app" if logged_in
             else "Login isn't set up, so anyone with the link could open it",
             "Add the Google login keys ([auth]) to the app's Streamlit secrets."),
        Step("ai", "AI key", bool(llm_key),
             "Set" if llm_key else "Missing",
             "Add OPENAI_API_KEY (or NVIDIA_API_KEY). It reads bank emails and answers "
             "questions on Best card / Ask."),
        Step("gmail", "Gmail reader", gmail_ok,
             (f"Last check: {gmail.message[:120]}" if gmail else "Hasn't run yet"),
             "Connect Gmail once (GMAIL_TOKEN_JSON in GitHub secrets). It checks every hour "
             "for bank emails about offers, purchases and credits. If your banks email a "
             "different address, forward those emails to this inbox."),
        Step("refresh", "Refresh now button", bool(secret("GITHUB_TOKEN")),
             "Ready" if secret("GITHUB_TOKEN") else "GITHUB_TOKEN is missing",
             "Add a GitHub token with Actions read & write so Refresh now can start a check."),
        Step("cards", "Your cards", bool(digits),
             f"{len(digits)} of {len(cards_config())} cards have last digits"
             if digits else "No last digits yet",
             "Enter last digits, your BofA 3% category and this quarter's Discover 5%.",
             page="views/my_cards.py"),
    ]
    for src, name in BANKS.items():
        run = latest_sync(s, src)
        ok = bool(run and run.status == "ok")
        out.append(Step(
            src, f"{name} offers", ok,
            "Not connected yet" if run is None else
            {"ok": f"Synced: {run.message}", "needs_code": "Waiting for a security code",
             "running": "Syncing now"}.get(run.status, f"Last try failed: {run.message[:120]}"),
            f"Save your {name} login on your Mac (it stays in your Keychain), then do one "
            "visible run. After that it runs every day at 7 AM by itself.",
            page="views/accounts.py",
            command=f".venv/bin/python -m robot.setup {src}\n"
                    f".venv/bin/python -m robot.runner --once --bank {src} --headed"))
    out.append(Step("offers", "First offers in", offers > 0,
                    f"{offers} offers saved" if offers else "No offers yet",
                    "Offers arrive from the bank robot and Gmail. You can also type one in.",
                    page="views/add.py"))
    return out

