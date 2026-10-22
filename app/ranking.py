"""Offer value, base rewards with caps, grades and "which card should I use" ranking.

Pure functions over plain data so they are easy to test. `offers` may be ORM Offer
rows or any object with the same attributes.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.config import cards_config, settings_config

POINT_VALUE = 0.01  # ponytail: flat 1 cent/point; per-program values if points offers show up


def quarter_key(on: date) -> str:
    return f"{on.year}Q{(on.month - 1) // 3 + 1}"


def period_start(period: str, on: date) -> date:
    if period == "year":
        return date(on.year, 1, 1)
    if period == "quarter":
        return date(on.year, 3 * ((on.month - 1) // 3) + 1, 1)
    if period == "month":
        return date(on.year, on.month, 1)
    raise ValueError(f"unknown cap period {period!r}")


def offer_value(offer: Any, amount: float) -> float:
    """Credit this offer pays on a purchase of `amount` (0 if below min spend)."""
    if offer.min_spend and amount < offer.min_spend:
        return 0.0
    if offer.type == "pct":
        value = amount * (offer.pct or 0) / 100
        if offer.max_credit:
            value = min(value, offer.max_credit)
    elif offer.type == "fixed":
        value = offer.fixed_amount or 0.0
    elif offer.type == "points":
        value = (offer.fixed_amount or 0) * POINT_VALUE
    else:
        raise ValueError(f"unknown offer type {offer.type!r}")
    return round(value, 2)


def offer_max_value(offer: Any) -> float:
    if offer.type == "pct":
        return float(offer.max_credit or 0)
    if offer.type == "points":
        return round((offer.fixed_amount or 0) * POINT_VALUE, 2)
    return float(offer.fixed_amount or 0)


def spend_for_full_credit(offer: Any) -> float | None:
    """How much to spend to get the whole credit."""
    if offer.type == "pct" and offer.pct and offer.max_credit:
        return round(max(offer.max_credit * 100 / offer.pct, offer.min_spend or 0), 2)
    return offer.min_spend


def grade(max_value: float) -> str:
    g = settings_config()["grades"]
    if max_value >= g["A"]:
        return "A"
    if max_value >= g["B"]:
        return "B"
    return "C"


def dedupe_key(issuer: str, card_id: str, merchant_norm: str, expires_on: date | None,
               value: str) -> str:
    """Same offer from email and robot -> same key."""
    return "|".join([issuer.lower(), card_id, merchant_norm.lower().strip(),
                     expires_on.isoformat() if expires_on else "", value])


def offer_value_label(type_: str, pct: float | None, fixed: float | None,
                      max_credit: float | None) -> str:
    if type_ == "pct":
        return f"{pct:g}%/{max_credit or 0:g}"
    return f"{type_}:{fixed or 0:g}"


@dataclass
class Rate:
    rate: float
    cap: str | None = None  # cap key in card's caps
    note: str = ""


def card_rate(card: dict, category: str, on: date) -> Rate:
    """Reward rate for a category before caps."""
    if card.get("rotating"):
        q = card["rotating"].get(quarter_key(on))
        if q and category in q["categories"]:
            if q.get("activated"):
                return Rate(card["rotating_rate"], "discover_rotating")
            return Rate(card["base_rate"], None, "5% rotating not activated")
    if card.get("choice_category") == category and "choice" in card["categories"]:
        c = card["categories"]["choice"]
        return Rate(c["rate"], c.get("cap"))
    c = card["categories"].get(category)
    if c:
        return Rate(c["rate"], c.get("cap"))
    return Rate(card["base_rate"], None, card.get("note", ""))


def base_value(card: dict, category: str, amount: float, on: date,
               cap_used: dict[str, float] | None = None) -> tuple[float, Rate]:
    """Base rewards on `amount`, splitting at the cap: bonus rate up to the cap, base after."""
    r = card_rate(card, category, on)
    if not r.cap:
        return round(amount * r.rate, 2), r
    used = (cap_used or {}).get(f"{card['id']}:{r.cap}", 0)
    remaining = max(card["caps"][r.cap]["limit"] - used, 0)
    bonus_part = min(amount, remaining)
    value = bonus_part * r.rate + (amount - bonus_part) * card["base_rate"]
    if bonus_part < amount:
        r = Rate(r.rate, r.cap, "cap reached")
    return round(value, 2), r


def cap_usage(txns: Iterable[tuple[str, str, float, date]], on: date) -> dict[str, float]:
    """Spend counted against each card cap in its current period.

    txns: (card_id, category, amount, date). Returns {"card_id:cap_key": spent}.
    """
    by_id = {c["id"]: c for c in cards_config()}
    used: dict[str, float] = {}
    for card_id, category, amount, d in txns:
        card = by_id.get(card_id)
        if not card:
            continue
        r = card_rate(card, category, d)
        if not r.cap:
            continue
        if period_start(card["caps"][r.cap]["period"], d) != period_start(
                card["caps"][r.cap]["period"], on):
            continue
        key = f"{card_id}:{r.cap}"
        used[key] = used.get(key, 0) + amount
    return used


@dataclass
class Option:
    card_id: str
    card_name: str
    total: float
    offer_value: float
    base_value: float
    base_rate: float
    offer: Any = None
    breakdown: str = ""
    warnings: list[str] = field(default_factory=list)


def _offer_ok(offer: Any, on: date) -> bool:
    # status is the caller's job (history views rank offers that were active back then)
    return offer.expires_on is None or offer.expires_on >= on


def rank_cards(amount: float, category: str, offers: Iterable[Any], on: date,
               cap_used: dict[str, float] | None = None) -> list[Option]:
    """All cards ranked by total value for this purchase. `offers` = offers at this merchant."""
    offers = [o for o in offers if _offer_ok(o, on)]
    out = []
    for card in cards_config():
        bv, r = base_value(card, category, amount, on, cap_used)
        best, best_v = None, 0.0
        for o in offers:
            if o.card_id == card["id"] and (v := offer_value(o, amount)) > best_v:
                best, best_v = o, v
        parts, warnings = [], []
        if best:
            if best.type == "pct":
                cap = f" (cap ${best.max_credit:g})" if best.max_credit else ""
                parts.append(f"Offer {best.pct:g}% = ${best_v:.2f}{cap}")
            else:
                parts.append(f"Offer ${best_v:.2f}")
            if not best.enrolled:
                warnings.append("Offer not added to card yet")
            if best.exclusions:
                warnings.append(f"Excludes: {best.exclusions}")
        else:
            near = [o for o in offers if o.card_id == card["id"] and o.min_spend]
            if near:
                o = min(near, key=lambda o: o.min_spend)
                warnings.append(f"Spend ${o.min_spend:g} to unlock {o.merchant_name} offer")
        parts.append(f"base {r.rate * 100:g}% = ${bv:.2f}")
        if r.note:
            warnings.append(r.note)
        out.append(Option(card["id"], card["name"], round(bv + best_v, 2), best_v, bv, r.rate,
                          best, " + ".join(parts), warnings))
    return sorted(out, key=lambda o: (-o.total, -o.offer_value))


def amex_best_card(card_ids: Iterable[str], category: str, on: date) -> str:
    """Amex offers enroll on one card only: pick the best base rate for the merchant category."""
    by_id = {c["id"]: c for c in cards_config()}
    return max(card_ids, key=lambda cid: card_rate(by_id[cid], category, on).rate)


BEST_CARD_CATEGORIES = ["groceries", "online", "gas", "dining", "travel", "wholesale", "other"]


def best_card_per_category(on: date) -> list[tuple[str, dict, Rate]]:
    out = []
    for cat in BEST_CARD_CATEGORIES:
        card = max(cards_config(), key=lambda c: card_rate(c, cat, on).rate)
        out.append((cat, card, card_rate(card, cat, on)))
    return out
