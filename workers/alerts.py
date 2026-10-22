"""Alert checks, run hourly. Every send is logged in AlertSent by dedupe key: never twice.

Times are America/New_York (DST-aware via zoneinfo). Quiet hours hold everything except the
MFA alert: we simply don't send, and the first run after quiet hours end sends it (its dedupe
key isn't recorded yet).
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import insights, ranking
from app.config import card_by_id, cards_config, secret, settings_config, tz
from app.db import (
    AlertSent,
    Credit,
    ExpectedCredit,
    Offer,
    Transaction,
    Watchlist,
    alert_settings,
    latest_sync,
)
from workers import emails

log = logging.getLogger(__name__)
Sender = Callable[[str, str, str, str], None]  # (to, subject, html, text)


def _default_send(to: str, subject: str, html: str, text: str) -> None:
    from workers.gmail_reader import send_email

    send_email(to, subject, html, text)


def recipient() -> str | None:
    return secret("ALERT_EMAIL") or secret("ALLOWED_EMAIL")


def app_url() -> str:
    return secret("APP_URL") or ""


def is_quiet(local: datetime) -> bool:
    q = settings_config()["quiet_hours"]
    return local.hour >= q["start"] or local.hour < q["end"]


def _sent(s: Session, key: str) -> bool:
    return s.scalar(select(AlertSent.id).where(AlertSent.dedupe_key == key)) is not None


def _send(s: Session, send: Sender, kind: str, keys: list[str],
          msg: tuple[str, str, str]) -> str | None:
    """Send once and record every key. Commits so a later crash can't cause a resend."""
    to = recipient()
    if not to:
        log.warning("no ALERT_EMAIL/ALLOWED_EMAIL; skipping %s", kind)
        return None
    subject, html, text = msg
    send(to, subject, html, text)
    s.add_all(AlertSent(kind=kind, dedupe_key=k, subject=subject) for k in keys)
    s.commit()
    return subject


def _bundle(s: Session, send: Sender, kind: str, items: list[tuple[str, str]], subject: str,
            title: str) -> str | None:
    """items = (dedupe_key, line). One email with every not-yet-sent item."""
    new = [(k, line) for k, line in items if not _sent(s, k)]
    if not new:
        return None
    subj = subject if len(new) == 1 else f"{subject} ({len(new)})"
    return _send(s, send, kind, [k for k, _ in new],
                 emails.simple_email(subj, title, [line for _, line in new], app_url()))


def _expiring(o: Offer, on: date) -> emails.ExpiringOffer:
    card = card_by_id(o.card_id)
    return emails.ExpiringOffer(
        merchant=o.merchant_name, offer_text=o.offer_text, card_name=card["name"],
        bank=card["issuer"], offers_url=card.get("offers_url"), expires_on=o.expires_on,
        days_left=(o.expires_on - on).days, max_value=ranking.offer_max_value(o),
        enrolled=o.enrolled, spend_for_full=ranking.spend_for_full_credit(o))


def expiry_digest(s: Session, on: date, send: Sender) -> str | None:
    """Offers expiring in exactly 3 or 1 days (still active = unused), bundled into one email."""
    key = f"digest:{on.isoformat()}"
    if _sent(s, key):
        return None
    offers = insights.active_offers(s, on)
    due = sorted((o for o in offers if o.expires_on and (o.expires_on - on).days in (1, 3)),
                 key=lambda o: ((o.expires_on - on).days, -ranking.offer_max_value(o)))
    if not due:
        return None
    soon = [o for o in offers if o.expires_on and o not in due
            and (o.expires_on - on).days <= 7]
    also = [_expiring(o, on) for o in due[1:] + sorted(soon, key=lambda o: o.expires_on)]
    watch = []
    for ec in s.scalars(select(ExpectedCredit).where(ExpectedCredit.status != "posted")):
        o, t = s.get(Offer, ec.offer_id), s.get(Transaction, ec.transaction_id)
        watch.append(emails.CreditWatch(o.merchant_name, ec.amount, t.date, ec.due_on, ec.status))
    return _send(s, send, "expiry_digest", [key],
                 emails.expiry_email(_expiring(due[0], on), also, watch, app_url()))


def mfa_alert(s: Session, send: Sender = _default_send) -> str | None:
    """Bank needs a security code. Also called by the robot the moment it hits MFA."""
    items = []
    for src in ("amex", "bofa", "wellsfargo"):
        run = latest_sync(s, src)
        if run and run.status == "needs_code":
            items.append((f"mfa:{run.id}", f"{src}: the bank robot is waiting for a "
                          "security code. Enter it on the Accounts page within 10 minutes."))
    return _bundle(s, send, "mfa_needed", items, "Bank needs a security code",
                   "Bank needs a security code")


def check(s: Session, now: datetime, send: Sender = _default_send) -> list[str]:
    """Run every enabled alert for this hour. Returns subjects sent."""
    local = now.astimezone(tz())
    on = local.date()
    cfg = alert_settings(s)
    sent: list[str | None] = []

    if cfg.get("mfa_needed"):  # immediate, ignores quiet hours
        sent.append(mfa_alert(s, send))

    if is_quiet(local):
        return [x for x in sent if x]

    if cfg.get("expiry_3day") and local.hour == settings_config()["digest_hour"]:
        sent.append(expiry_digest(s, on, send))

    offers = insights.active_offers(s, on)
    if cfg.get("new_high_value"):
        min_v = float(cfg.get("high_value_min", 20))
        since = now.astimezone(UTC).replace(tzinfo=None) - timedelta(days=2)
        items = [(f"new_offer:{o.id}", _offer_line(o)) for o in offers
                 if o.first_seen_at >= since and ranking.offer_max_value(o) >= min_v]
        sent.append(_bundle(s, send, "new_high_value", items, "New high-value offer",
                            "New high-value offers"))

    if cfg.get("watchlist_match"):
        watch = [insights.norm(w) for w in s.scalars(select(Watchlist.merchant_name))]
        items = [(f"watch:{o.id}", _offer_line(o)) for o in offers
                 if any(_matches(o.merchant_name, w) for w in watch)]
        sent.append(_bundle(s, send, "watchlist_match", items, "Watchlist match",
                            "Offers at merchants you watch"))

    if cfg.get("credit_posted"):
        items = [(f"credit:{c.id}", f"{c.merchant_raw}: {emails.money(c.amount)} credit on "
                  f"{card_by_id(c.card_id)['name']} ({c.date:%b %-d})")
                 for c in s.scalars(select(Credit).where(Credit.date >= on - timedelta(days=7)))]
        sent.append(_bundle(s, send, "credit_posted", items, "Credit posted", "Credits posted"))

    if cfg.get("credit_overdue"):
        items = []
        for ec in s.scalars(select(ExpectedCredit).where(ExpectedCredit.status == "overdue")):
            o, t = s.get(Offer, ec.offer_id), s.get(Transaction, ec.transaction_id)
            items.append((f"overdue:{ec.id}", (
                f"{o.merchant_name}: expected {emails.money(ec.amount)} by {ec.due_on:%b %-d}. "
                f"Purchase {t.date:%b %-d}, {emails.money(t.amount)} on "
                f"{card_by_id(t.card_id)['name']}. Offer: {o.offer_text}")))
        sent.append(_bundle(s, send, "credit_overdue", items, "Credit overdue",
                            "Credits overdue: send these details to the bank"))

    if cfg.get("rotating_reminder"):
        items = []
        q = ranking.quarter_key(on)
        for c in cards_config():
            rot = (c.get("rotating") or {}).get(q)
            if rot and not rot.get("activated"):
                cats = ", ".join(rot["categories"])
                items.append((f"rotating:{c['id']}:{q}", f"Activate {c['name']} "
                              f"{c['rotating_rate'] * 100:g}% for {q}: {cats}"))
            if c.get("choice_category"):
                items.append((f"choice:{c['id']}:{on:%Y-%m}", f"Review {c['name']} choice "
                              f"category (now: {c['choice_category']})"))
        sent.append(_bundle(s, send, "rotating_reminder", items, "Card category reminder",
                            "Card category reminders"))

    if cfg.get("weekly_summary") and local.weekday() == 6 and local.hour == 9:
        k = insights.kpis(s, on)
        lines = [f"Value on your cards: {emails.money(k.value_total)}",
                 f"Not added yet: {emails.money(k.not_added_value)} ({k.not_added_count})",
                 "Expiring in 7 days: "
                 + (", ".join(o.merchant_name for o in k.expiring_7) or "none"),
                 f"Saved this year: {emails.money(k.saved_this_year)}"]
        if not _sent(s, key := f"weekly:{on}"):
            sent.append(_send(s, send, "weekly_summary", [key], emails.simple_email(
                "Weekly card offers summary", "This week", lines, app_url())))
    return [x for x in sent if x]


def _offer_line(o: Offer) -> str:
    exp = f", expires {o.expires_on:%b %-d}" if o.expires_on else ""
    return (f"{o.merchant_name}: {o.offer_text} (up to {emails.money(ranking.offer_max_value(o))}"
            f" on {card_by_id(o.card_id)['name']}{exp})")


def _matches(merchant: str, watched: str) -> bool:
    n = insights.norm(merchant)
    return n == watched or n.startswith(watched + " ")


def monthly_recap(s: Session, now: datetime, send: Sender = _default_send) -> str | None:
    """Recap of the previous month (run on the 1st)."""
    if not alert_settings(s).get("monthly_recap"):
        return None
    end = now.astimezone(tz()).date().replace(day=1)
    start = (end - timedelta(days=1)).replace(day=1)
    key = f"monthly:{start:%Y-%m}"
    if _sent(s, key):
        return None
    credits = list(s.scalars(select(Credit).where(Credit.date >= start, Credit.date < end)))
    ids = {c.id for c in credits}
    used = {c.offer_id for c in credits if c.offer_id} | set(s.scalars(
        select(ExpectedCredit.offer_id).where(ExpectedCredit.credit_id.in_(ids))))
    misses = [m for m in insights.missed_savings(s, start) if m.txn.date < end]
    new = sorted(s.scalars(select(Offer).where(Offer.first_seen_at >= start,
                                               Offer.first_seen_at < end)),
                 key=lambda o: -ranking.offer_max_value(o))[:5]
    sections = {
        "Offers used": [s.get(Offer, i).merchant_name for i in used],
        "Credits posted": [f"{c.merchant_raw}: {emails.money(c.amount)} ({c.date:%b %-d})"
                           for c in credits],
        "Top missed savings": [f"{m.merchant} on {card_by_id(m.txn.card_id)['name']}: missed "
                               f"{emails.money(m.missed)}, {m.best.card_name} was better"
                               for m in sorted(misses, key=lambda m: -m.missed)[:5]],
        "Top new offers": [_offer_line(o) for o in new],
    }
    totals = {"Credits posted": sum(c.amount for c in credits),
              "Missed savings": sum(m.missed for m in misses)}
    return _send(s, send, "monthly_recap", [key],
                 emails.recap_email(f"{start:%B %Y}", sections, totals, app_url()))

