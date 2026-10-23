"""Merchant normalization, card mapping, offer upsert/dedupe, transactions and credits."""

import logging
from datetime import date
from typing import Any

from pydantic import BaseModel
from rapidfuzz import fuzz, process
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import llm, ranking
from app.config import cards_config, settings_config
from app.db import Credit, Merchant, MerchantAlias, Offer, Transaction, utcnow
from app.insights import norm, today
from workers.extract import Classification

log = logging.getLogger(__name__)

ISSUER_BY_DOMAIN = {
    "americanexpress.com": "American Express", "aexp.com": "American Express",
    "bankofamerica.com": "Bank of America", "wellsfargo.com": "Wells Fargo",
    "discover.com": "Discover", "synchronybank.com": "Synchrony", "synchrony.com": "Synchrony",
    "apple.com": "Apple", "goldmansachs.com": "Apple",
}
CATEGORIES = ["groceries", "online", "gas", "dining", "travel", "wholesale", "drugstores",
              "entertainment", "home_improvement", "other"]


class MerchantPick(BaseModel):
    existing: str = "new"  # exact canonical name from the list, or "new"
    name: str = ""  # clean canonical name when new
    category: str = "other"


MERCHANT_SYSTEM = f"""Map a raw merchant name from a bank email or card statement to one of the
EXISTING canonical merchants if it is the same business (existing = that exact name).
Otherwise existing = "new", name = the clean brand name (e.g. "UBER *TRIP" -> "Uber"),
category = one of {", ".join(CATEGORIES)}."""


def _alias(s: Session, alias: str, m: Merchant) -> Merchant:
    s.add(MerchantAlias(alias=alias, merchant_id=m.id))
    s.flush()
    return m


def merchant_for(s: Session, raw: str, category: str | None = None) -> Merchant:
    """Alias table -> exact/fuzzy canonical name -> LLM fallback. Learned aliases persist.
    `category` given (manual entry): skip the LLM and create the merchant with it."""
    n = norm(raw)
    if a := s.scalar(select(MerchantAlias).where(MerchantAlias.alias == n)):
        return s.get(Merchant, a.merchant_id)
    merchants = list(s.scalars(select(Merchant)))
    names = {m.id: norm(m.name) for m in merchants}
    best = process.extractOne(n, names, scorer=fuzz.ratio,
                              score_cutoff=settings_config()["fuzzy_threshold"])
    if best:
        return _alias(s, n, next(m for m in merchants if m.id == best[2]))
    pick = MerchantPick(name=raw.strip(), category=category or "other")
    if merchants and category is None:
        try:
            pick = llm.complete_json(MERCHANT_SYSTEM, f"EXISTING: {sorted(names.values())}\n"
                                                      f"RAW: {raw}", MerchantPick)
        except llm.LLMValidationError:
            log.warning("merchant LLM fallback failed; creating new merchant")
    by_norm = {norm(m.name): m for m in merchants}
    if m := by_norm.get(norm(pick.existing)):
        return _alias(s, n, m)
    name = (pick.name or raw).strip()[:120]
    if m := by_norm.get(norm(name)):
        return _alias(s, n, m)
    m = Merchant(name=name, category=pick.category if pick.category in CATEGORIES else "other")
    s.add(m)
    s.flush()
    return _alias(s, n, m)


def issuer_for_sender(sender: str) -> str | None:
    domain = sender.rpartition("@")[2].lower()
    return next((v for d, v in ISSUER_BY_DOMAIN.items()
                 if domain == d or domain.endswith("." + d)), None)


def card_for(last_digits: str | None, issuer: str | None) -> str | None:
    """cards.yaml last_digits first, else the issuer's (first) card."""
    d = "".join(ch for ch in (last_digits or "") if ch.isdigit())
    if d:
        for c in cards_config():
            ld = str(c.get("last_digits") or "")
            if ld and (ld.endswith(d) or d.endswith(ld)):
                return c["id"]
    return next((c["id"] for c in cards_config() if c["issuer"] == issuer), None)


def _key(issuer: str, card_id: str, m: Merchant, o: Any) -> str:
    value = ranking.offer_value_label(o.type, o.pct, o.fixed_amount, o.max_credit)
    return ranking.dedupe_key(issuer, card_id, m.name, o.expires_on, value)


def upsert_offer(s: Session, issuer: str, card_id: str, o: Any, source: str,
                 source_ref: str | None) -> Offer:
    """Insert or refresh one offer. `o` is an OfferX or anything with the same attributes
    (optional `enrolled`). Same offer from email and robot -> one row (ranking.dedupe_key)."""
    m = merchant_for(s, o.merchant)
    if issuer == "American Express":  # enrolls on one card only: keep it on the best one
        amex = [c["id"] for c in cards_config() if c["issuer"] == issuer]
        keys = [_key(issuer, c, m, o) for c in amex if c != card_id]
        twins = list(s.scalars(select(Offer).where(Offer.dedupe_key.in_(keys))))
        if twins:
            best = ranking.amex_best_card([card_id, *[t.card_id for t in twins]], m.category,
                                          today())
            card_id = best
            for t in twins:
                if t.card_id != best:
                    s.delete(t)
            s.flush()
    key = _key(issuer, card_id, m, o)
    now = utcnow()
    row = s.scalar(select(Offer).where(Offer.dedupe_key == key))
    if row is None:
        row = Offer(dedupe_key=key, issuer=issuer, card_id=card_id, merchant_id=m.id,
                    merchant_name=m.name, type=o.type, pct=o.pct, fixed_amount=o.fixed_amount,
                    min_spend=o.min_spend, max_credit=o.max_credit, expires_on=o.expires_on,
                    source=source, source_ref=source_ref, first_seen_at=now)
        s.add(row)
    row.last_seen_at = now
    row.offer_text = o.offer_text or row.offer_text or ""
    row.channel = getattr(o, "channel", None) or row.channel or "both"
    row.exclusions = o.exclusions or row.exclusions or ""
    if (enrolled := getattr(o, "enrolled", None)) is not None:
        row.enrolled = bool(enrolled)
    s.flush()
    return row


def apply(s: Session, sender: str, c: Classification, message_id: str) -> dict[str, int]:
    """Write one email's extraction. Idempotent per message_id."""
    issuer = issuer_for_sender(sender)
    n = {"offers": 0, "transactions": 0, "credits": 0}
    for o in c.offers:
        if issuer and (card := card_for(o.card_last_digits, issuer)):
            upsert_offer(s, issuer, card, o, "email", message_id)
            n["offers"] += 1
    for i, t in enumerate(c.transactions):
        ref = f"{message_id}#{i}"
        card = card_for(t.card_last_digits, issuer)
        if card and not s.scalar(select(Transaction.id)
                                 .where(Transaction.source_message_id == ref)):
            m = merchant_for(s, t.merchant_raw)
            s.add(Transaction(card_id=card, merchant_raw=t.merchant_raw, merchant_id=m.id,
                              amount=t.amount, date=t.date, source_message_id=ref))
            n["transactions"] += 1
    for i, cr in enumerate(c.credits):
        ref = f"{message_id}#{i}"
        card = card_for(cr.card_last_digits, issuer)
        if card and not s.scalar(select(Credit.id).where(Credit.source_message_id == ref)):
            m = merchant_for(s, cr.merchant)
            offer_id = s.scalar(select(Offer.id).where(Offer.card_id == card,
                                                       Offer.merchant_id == m.id)
                                .order_by(Offer.last_seen_at.desc()))
            s.add(Credit(card_id=card, merchant_raw=cr.merchant, merchant_id=m.id,
                         amount=cr.amount, date=cr.date, offer_id=offer_id,
                         source_message_id=ref))
            n["credits"] += 1
    s.flush()
    return n


def expire_offers(s: Session, on: date | None = None) -> int:
    r = s.execute(update(Offer).where(Offer.status == "active", Offer.expires_on < (on or today()))
                  .values(status="expired"))
    return r.rowcount
