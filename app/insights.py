"""DB-backed views shared by the UI and workers: KPIs, to-dos, missed savings,
credit watchdog and spend progress."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ranking
from app.config import cards_config, settings_config, tz
from app.db import (
    Card,
    Credit,
    ExpectedCredit,
    Merchant,
    Offer,
    SyncRun,
    TodoDone,
    Transaction,
    latest_sync,
)


def today() -> date:
    return datetime.now(tz()).date()


def norm(name: str) -> str:
    return " ".join(name.lower().split())


def categories(s: Session) -> dict[int, str]:
    return dict(s.execute(select(Merchant.id, Merchant.category)).all())


def merchant_category(s: Session, merchant_name: str) -> str:
    m = s.scalar(select(Merchant).where(Merchant.name.ilike(merchant_name.strip())))
    return m.category if m else "other"


def active_offers(s: Session, on: date | None = None) -> list[Offer]:
    on = on or today()
    return list(s.scalars(
        select(Offer).where(Offer.status == "active",
                            (Offer.expires_on.is_(None)) | (Offer.expires_on >= on))
    ))


def offers_for_merchant(s: Session, merchant_name: str, on: date | None = None) -> list[Offer]:
    """Exact match first; else partial ("uber" finds "Uber Eats")."""
    n = norm(merchant_name)
    offers = active_offers(s, on)
    exact = [o for o in offers if norm(o.merchant_name) == n]
    return exact or [o for o in offers if n and (n in norm(o.merchant_name)
                                                  or norm(o.merchant_name) in n)]


def cap_used_now(s: Session, on: date | None = None) -> dict[str, float]:
    on = on or today()
    cats = categories(s)
    txns = s.scalars(select(Transaction).where(Transaction.date >= date(on.year - 1, 1, 1)))
    return ranking.cap_usage(
        ((t.card_id, cats.get(t.merchant_id, "other"), t.amount, t.date) for t in txns), on)


def best_for_purchase(s: Session, merchant_name: str, amount: float,
                      on: date | None = None) -> list[ranking.Option]:
    on = on or today()
    return ranking.rank_cards(amount, merchant_category(s, merchant_name),
                              offers_for_merchant(s, merchant_name, on), on, cap_used_now(s, on))


def shopped_merchants(s: Session, on: date | None = None) -> set[str]:
    on = on or today()
    since = on - timedelta(days=settings_config()["you_shop_here_days"])
    names = s.scalars(
        select(Merchant.name).join(Transaction, Transaction.merchant_id == Merchant.id)
        .where(Transaction.date >= since))
    return {norm(n) for n in names}


def previous_sync_start(s: Session) -> datetime | None:
    """"New" = first seen since the previous sync (the one before the latest)."""
    runs = s.scalars(select(SyncRun.started_at).where(SyncRun.status == "ok")
                     .order_by(SyncRun.started_at.desc()).limit(2)).all()
    return runs[-1] if runs else None


def is_new(offer: Offer, prev_sync: datetime | None) -> bool:
    return prev_sync is None or offer.first_seen_at >= prev_sync


@dataclass
class Kpis:
    value_total: float
    not_added_value: float
    not_added_count: int
    expiring_7: list[Offer]
    saved_this_year: float


def kpis(s: Session, on: date | None = None) -> Kpis:
    on = on or today()
    offers = active_offers(s, on)
    not_added = [o for o in offers if not o.enrolled]
    saved = sum(s.scalars(select(Credit.amount).where(Credit.date >= date(on.year, 1, 1))))
    return Kpis(
        value_total=round(sum(ranking.offer_max_value(o) for o in offers), 2),
        not_added_value=round(sum(ranking.offer_max_value(o) for o in not_added), 2),
        not_added_count=len(not_added),
        expiring_7=sorted([o for o in offers if o.expires_on and o.expires_on <= on
                           + timedelta(days=7)], key=lambda o: o.expires_on),
        saved_this_year=round(saved, 2),
    )


@dataclass
class Todo:
    key: str
    title: str
    detail: str
    action: str = ""  # link URL or "" (page handles code entry etc.)
    kind: str = "info"  # add_offer | mfa | activate | review | inactive


def todos(s: Session, on: date | None = None) -> list[Todo]:
    on = on or today()
    out: list[Todo] = []
    cards = {c["id"]: c for c in cards_config()}
    for o in active_offers(s, on):
        if not o.enrolled and ranking.grade(ranking.offer_max_value(o)) in ("A", "B"):
            card_name = cards[o.card_id]["name"]
            out.append(Todo(f"add:{o.id}", f"Add {o.merchant_name} offer",
                            f"Up to ${ranking.offer_max_value(o):.0f} on {card_name}",
                            cards[o.card_id].get("offers_url") or "", "add_offer"))
    for src in ("amex", "bofa", "wellsfargo"):
        run = latest_sync(s, src)
        if run and run.status == "needs_code":
            out.append(Todo(f"mfa:{run.id}", f"Enter {src} security code",
                            "The bank robot is waiting for a code", "", "mfa"))
    q = ranking.quarter_key(on)
    disc = cards.get("discover_it")
    if disc and (rot := disc.get("rotating", {}).get(q)) and not rot.get("activated"):
        out.append(Todo(f"activate:{q}", "Activate Discover 5%",
                        f"{q}: {', '.join(rot['categories'])}", disc.get("offers_url") or "",
                        "activate"))
    if "bofa_ccr" in cards:
        out.append(Todo(f"bofa_choice:{on:%Y-%m}", "Review BofA 3% category",
                        f"Currently: {cards['bofa_ccr'].get('choice_category')}",
                        cards["bofa_ccr"].get("offers_url") or "", "review"))
    cutoff = on - timedelta(days=settings_config()["inactive_card_days"])
    used = set(s.scalars(select(Transaction.card_id).where(Transaction.date >= cutoff)))
    for c in s.scalars(select(Card)):
        if c.id not in used:
            out.append(Todo(f"inactive:{c.id}:{on:%Y-%m}", f"Use your {c.name}",
                            "No purchase in 90 days — keep it active", "", "inactive"))
    done = set(s.scalars(select(TodoDone.key)))
    return [t for t in out if t.key not in done]


@dataclass
class Miss:
    txn: Transaction
    merchant: str
    earned: float
    best: ranking.Option
    missed: float


def _offers_on(offers: list[Offer], d: date) -> list[Offer]:
    return [o for o in offers if o.first_seen_at.date() <= d
            and (o.expires_on is None or o.expires_on >= d)]


def missed_savings(s: Session, since: date) -> list[Miss]:
    """For each transaction: what I earned vs. the best card+offer on that date."""
    cats = categories(s)
    names = dict(s.execute(select(Merchant.id, Merchant.name)).all())
    all_offers = list(s.scalars(select(Offer)))
    out = []
    for t in s.scalars(select(Transaction).where(Transaction.date >= since)
                       .order_by(Transaction.date)):
        merchant = names.get(t.merchant_id, t.merchant_raw)
        offers = [o for o in _offers_on(all_offers, t.date) if norm(o.merchant_name) == norm(
            merchant)]
        opts = ranking.rank_cards(t.amount, cats.get(t.merchant_id, "other"), offers, t.date)
        earned = next((o.total for o in opts if o.card_id == t.card_id), 0.0)
        missed = round(opts[0].total - earned, 2)
        if missed > 0.0:
            out.append(Miss(t, merchant, earned, opts[0], missed))
    return out


def missed_by_month(misses: list[Miss]) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in misses:
        k = m.txn.date.strftime("%Y-%m")
        out[k] = round(out.get(k, 0) + m.missed, 2)
    return out


def create_expected_credits(s: Session) -> int:
    """Credit watchdog: a purchase that qualifies for an added offer expects a credit."""
    due_days = settings_config()["credit_due_days"]
    names = dict(s.execute(select(Merchant.id, Merchant.name)).all())
    have = set(s.scalars(select(ExpectedCredit.transaction_id)))
    enrolled = list(s.scalars(select(Offer).where(Offer.enrolled.is_(True))))
    n = 0
    for t in s.scalars(select(Transaction)):
        if t.id in have:
            continue
        merchant = norm(names.get(t.merchant_id, t.merchant_raw))
        for o in enrolled:
            if (o.card_id == t.card_id and norm(o.merchant_name) == merchant
                    and (o.expires_on is None or t.date <= o.expires_on)
                    and o.first_seen_at.date() <= t.date
                    and (v := ranking.offer_value(o, t.amount)) > 0):
                s.add(ExpectedCredit(transaction_id=t.id, offer_id=o.id, amount=v,
                                     due_on=t.date + timedelta(days=due_days)))
                n += 1
                break
    s.flush()
    return n


def update_expected_credits(s: Session, on: date | None = None) -> list[ExpectedCredit]:
    """Match posted credits, flag overdue ones. Returns newly overdue."""
    on = on or today()
    used_credit_ids = set(s.scalars(select(ExpectedCredit.credit_id)
                                    .where(ExpectedCredit.credit_id.is_not(None))))
    newly_overdue = []
    for ec in s.scalars(select(ExpectedCredit).where(ExpectedCredit.status != "posted")):
        offer = s.get(Offer, ec.offer_id)
        txn = s.get(Transaction, ec.transaction_id)
        credits = s.scalars(select(Credit).where(Credit.card_id == txn.card_id,
                                                 Credit.date >= txn.date))
        match = next((c for c in credits if c.id not in used_credit_ids and (
            c.offer_id == offer.id or norm(c.merchant_raw) in norm(offer.merchant_name)
            or norm(offer.merchant_name) in norm(c.merchant_raw))), None)
        if match:
            ec.status, ec.credit_id = "posted", match.id
            used_credit_ids.add(match.id)
            offer.status = "used"
        elif ec.due_on < on and ec.status != "overdue":
            ec.status = "overdue"
            newly_overdue.append(ec)
    s.flush()
    return newly_overdue


@dataclass
class SpendProgress:
    offer: Offer
    spent: float
    target: float


def spend_progress(s: Session, on: date | None = None) -> list[SpendProgress]:
    names = dict(s.execute(select(Merchant.id, Merchant.name)).all())
    out = []
    for o in active_offers(s, on):
        if not o.min_spend:
            continue
        spent = sum(t.amount for t in s.scalars(
            select(Transaction).where(Transaction.card_id == o.card_id,
                                      Transaction.date >= o.first_seen_at.date()))
            if norm(names.get(t.merchant_id, t.merchant_raw)) == norm(o.merchant_name))
        out.append(SpendProgress(o, round(spent, 2), o.min_spend))
    return out


def credits_by_month(s: Session, year: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for c in s.scalars(select(Credit).where(Credit.date >= date(year, 1, 1))):
        k = c.date.strftime("%Y-%m")
        out[k] = round(out.get(k, 0) + c.amount, 2)
    return out
