"""DEMO_MODE seed data so the UI works without real bank data."""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ranking
from app.db import Credit, Merchant, Offer, SyncRun, Transaction, Watchlist, sync_cards, utcnow
from app.insights import create_expected_credits, today

MERCHANTS = {
    "Dell": "online", "Hilton": "travel", "Groupon": "online", "Lyft": "travel",
    "Under Armour": "online", "Uber Eats": "dining", "Costco": "wholesale",
    "Whole Foods": "groceries", "Shell": "gas", "Amazon": "online", "Starbucks": "dining",
}

ISSUER = {"amex_bce": "American Express", "bofa_ccr": "Bank of America",
          "wf_visa_sig": "Wells Fargo"}


def _offers(on: date) -> list[dict]:
    year = on.year
    return [
        dict(merchant="Dell", card="amex_bce", type="fixed", fixed=60, min_spend=300,
             expires=date(year, 10, 31), text="Spend $300 or more, get $60 back"),
        dict(merchant="Hilton", card="amex_bce", type="fixed", fixed=50, min_spend=250,
             expires=on + timedelta(days=40), text="Spend $250+ on a stay, get $50 back"),
        dict(merchant="Groupon", card="bofa_ccr", type="pct", pct=15, max_credit=20,
             expires=on + timedelta(days=3), text="15% cash back, up to $20"),
        dict(merchant="Lyft", card="wf_visa_sig", type="pct", pct=10, max_credit=15,
             expires=on + timedelta(days=25), text="10% back on rides, up to $15",
             exclusions="Lyft Pink membership", first_seen=on - timedelta(days=10)),
        dict(merchant="Under Armour", card="amex_bce", type="pct", pct=20, max_credit=10,
             expires=date(year, 11, 8), text="Get 20% back, up to $10", enrolled=True,
             first_seen=on - timedelta(days=20)),
        dict(merchant="Uber Eats", card="bofa_ccr", type="fixed", fixed=5, min_spend=25,
             expires=on + timedelta(days=14), text="$5 back on $25+",
             exclusions="Purchases via PayPal or Apple Pay"),
    ]


def seed(s: Session) -> None:
    """Idempotent: does nothing if demo offers exist."""
    sync_cards(s)
    if s.scalar(select(Offer.id).where(Offer.source == "demo").limit(1)):
        return
    on = today()
    m = {}
    for name, cat in MERCHANTS.items():
        m[name] = s.scalar(select(Merchant).where(Merchant.name == name)) or Merchant(
            name=name, category=cat)
        s.add(m[name])
    s.flush()

    for o in _offers(on):
        issuer = ISSUER[o["card"]]
        value = ranking.offer_value_label(o["type"], o.get("pct"), o.get("fixed"),
                                          o.get("max_credit"))
        first_seen = datetime.combine(o.get("first_seen", on), datetime.min.time())
        s.add(Offer(
            dedupe_key=ranking.dedupe_key(issuer, o["card"], o["merchant"], o["expires"], value),
            issuer=issuer, card_id=o["card"], merchant_id=m[o["merchant"]].id,
            merchant_name=o["merchant"], offer_text=o["text"], type=o["type"], pct=o.get("pct"),
            fixed_amount=o.get("fixed"), min_spend=o.get("min_spend"),
            max_credit=o.get("max_credit"), expires_on=o["expires"],
            exclusions=o.get("exclusions", ""), source="demo", enrolled=o.get("enrolled", False),
            first_seen_at=first_seen, last_seen_at=utcnow()))

    txns = [
        ("Lyft", "discover_it", 45.00, 2), ("Under Armour", "amex_bce", 50.00, 12),
        ("Costco", "bofa_ccr", 182.40, 5), ("Whole Foods", "amex_bce", 96.15, 3),
        ("Shell", "amex_bce", 41.20, 8), ("Amazon", "bofa_ccr", 63.99, 15),
        ("Starbucks", "apple_card", 6.45, 1), ("Lyft", "discover_it", 22.00, 30),
        ("Dell", "amex_bce", 120.00, 6),
    ]
    for merchant, card, amount, days_ago in txns:
        s.add(Transaction(card_id=card, merchant_raw=merchant.upper(),
                          merchant_id=m[merchant].id, amount=amount,
                          date=on - timedelta(days=days_ago)))
    for merchant, card, amount, days_ago in [("Amazon", "amex_bce", 15.00, 45),
                                             ("Starbucks", "bofa_ccr", 3.00, 70),
                                             ("Hilton", "amex_bce", 50.00, 120)]:
        s.add(Credit(card_id=card, merchant_raw=merchant, merchant_id=m[merchant].id,
                     amount=amount, date=on - timedelta(days=days_ago)))
    for name in ("Costco", "Apple", "Delta"):
        if not s.scalar(select(Watchlist).where(Watchlist.merchant_name == name)):
            s.add(Watchlist(merchant_name=name))
    now = utcnow()
    s.add_all([
        SyncRun(source="gmail", started_at=now - timedelta(hours=26),
                finished_at=now - timedelta(hours=26), status="ok", message="Demo"),
        SyncRun(source="gmail", started_at=now - timedelta(minutes=40),
                finished_at=now - timedelta(minutes=39), status="ok", message="Demo: 3 emails"),
        SyncRun(source="amex", started_at=now - timedelta(hours=3),
                finished_at=now - timedelta(hours=3), status="ok", message="Demo: 3 offers"),
        SyncRun(source="bofa", started_at=now - timedelta(minutes=5), status="needs_code",
                message="Demo: waiting for security code"),
        SyncRun(source="wellsfargo", started_at=now - timedelta(days=3),
                finished_at=now - timedelta(days=3), status="ok", message="Demo"),
    ])
    s.flush()
    create_expected_credits(s)
