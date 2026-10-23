""""Refresh now" (GitHub workflow_dispatch + robot refresh request) and per-source status."""

from datetime import UTC, datetime

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import secret, settings_config, tz
from app.db import RefreshRequest, SyncRun, latest_sync, session, utcnow

SOURCES = {"gmail": "Gmail", "amex": "Amex", "bofa": "BofA", "wellsfargo": "Wells Fargo"}
BANKS = ("amex", "bofa", "wellsfargo")


def local_time(dt: datetime, now: datetime | None = None) -> str:
    """Naive-UTC DB time -> "7:02 AM" (today) or "Oct 20, 7:02 AM" in America/New_York."""
    t = dt.replace(tzinfo=UTC).astimezone(tz())
    n = (now or utcnow()).replace(tzinfo=UTC).astimezone(tz())
    clock = f"{t:%I:%M %p}".lstrip("0")
    return clock if t.date() == n.date() else f"{t:%b} {t.day}, {clock}"


def request_refresh() -> list[str]:
    """Ask the home robot (DB row) and GitHub Actions (Gmail) to sync now."""
    msgs = []
    try:
        with session() as s:
            s.add(RefreshRequest(source="all"))
        msgs.append("Banks: sync requested. Your Mac picks it up within 2 minutes if it's "
                    "on and automatic sync is turned on in the Card Offers Helper.")
    except Exception as e:
        msgs.append(f"Banks: could not save the refresh request ({type(e).__name__}).")
    token, repo = secret("GITHUB_TOKEN"), secret("GITHUB_REPO")
    if not token or not repo:
        msgs.append("Gmail: checks every hour by itself. Starting it from here needs the "
                    "GitHub token (Get started, Refresh now button).")
        return msgs
    url = f"https://api.github.com/repos/{repo}/actions/workflows/hourly.yml/dispatches"
    try:
        r = requests.post(url, json={"ref": "main"}, timeout=10, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
    except requests.RequestException as e:
        msgs.append(f"Gmail: could not reach GitHub ({type(e).__name__}). Try again shortly.")
        return msgs
    if r.status_code == 204:
        msgs.append("Gmail: sync started on GitHub Actions (takes about 1-2 minutes).")
    elif r.status_code in (401, 403):
        msgs.append(f"Gmail: GitHub refused the request ({r.status_code}). Check that "
                    "GITHUB_TOKEN is valid and has Actions write access to the repo.")
    else:
        msgs.append(f"Gmail: GitHub returned {r.status_code}: {r.text[:200]}")
    return msgs


def source_status(s: Session, now: datetime | None = None) -> dict[str, tuple[str, str]]:
    """{source: (label, pill tone)}, e.g. ("Amex: synced 7:02 AM", "green")."""
    now = now or utcnow()
    stale_hours = settings_config()["stale_hours"]
    out = {}
    for src, name in SOURCES.items():
        run = latest_sync(s, src)
        last_ok = s.scalar(select(SyncRun.finished_at).where(
            SyncRun.source == src, SyncRun.status == "ok", SyncRun.finished_at.is_not(None))
            .order_by(SyncRun.finished_at.desc()).limit(1))
        stale = ""
        if last_ok and (age := (now - last_ok).total_seconds() / 3600) > stale_hours:
            days = int(age // 24)
            stale = f"Last updated {days} day{'s' if days != 1 else ''} ago"
        if run is None:
            out[src] = (f"{name}: never synced", "gray")
        elif run.status == "running":
            out[src] = (f"{name}: syncing…", "blue")
        elif run.status == "needs_code":
            out[src] = (f"{name}: needs security code", "amber")
        elif run.status == "error":
            msg = (run.message or "unknown error")[:120]
            out[src] = (f"{name}: error: {msg}" + (f" ({stale})" if stale else ""), "amber")
        elif stale:
            out[src] = (f"{name}: {stale}", "amber")
        else:
            out[src] = (f"{name}: synced {local_time(run.finished_at or run.started_at, now)}",
                        "green")
    return out


def gmail_hint(run: SyncRun | None) -> str | None:
    """Plain-language fix for a broken Gmail reader, if any."""
    if run is None:
        return "Gmail reader has not run yet. See README, 'Gmail setup'."
    if run.status == "error" and "token" in (run.message or "").lower():
        return ("Gmail token expired — reconnect: rerun the Gmail OAuth setup script from "
                "the README ('Gmail setup') and update the token in secrets.")
    return None
