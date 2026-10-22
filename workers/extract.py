"""One LLM call per bank email: classify + extract offers / transactions / credits.

Results are cached in EmailProcessed.result_json by Gmail message_id, so no email is sent to
the LLM twice. Two validation failures -> status needs_review.
"""

import datetime as dt
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from app import llm
from app.db import EmailProcessed


class _X(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_blanks(cls, v: Any) -> Any:  # "" / null -> field default
        return {k: x for k, x in v.items() if x not in ("", None)} if isinstance(v, dict) else v


class OfferX(_X):
    merchant: str
    offer_text: str = ""
    type: Literal["pct", "fixed", "points"]
    pct: float | None = None  # 20 means 20%
    fixed_amount: float | None = None  # $ for fixed, points count for points
    min_spend: float | None = None
    max_credit: float | None = None
    expires_on: dt.date | None = None
    card_last_digits: str | None = None
    channel: Literal["online", "in_store", "both"] = "both"
    exclusions: str = ""
    source_message_id: str = ""


class TransactionX(_X):
    merchant_raw: str
    amount: float
    date: dt.date
    card_last_digits: str | None = None


class CreditX(_X):
    merchant: str
    amount: float
    date: dt.date
    card_last_digits: str | None = None
    offer_reference: str | None = None


class Classification(_X):
    type: Literal["offer_new", "offer_reminder", "transaction_alert", "credit_posted",
                  "statement", "other"]
    offers: list[OfferX] = []
    transactions: list[TransactionX] = []
    credits: list[CreditX] = []


SYSTEM = """You read one email from a credit card issuer and extract facts as JSON.
type: offer_new (new card-linked offers), offer_reminder (reminder about existing offers),
transaction_alert (a purchase was charged), credit_posted (a statement credit from an offer
posted), statement (statement ready / payment due), other.
offers: every card-linked merchant offer. pct offers: pct=20 for 20% and max_credit=cap.
fixed offers ("spend $300, get $60 back"): fixed_amount=60, min_spend=300. points offers:
fixed_amount=number of points. expires_on as YYYY-MM-DD. card_last_digits: digits only.
channel: online, in_store or both. exclusions: e.g. third-party, PayPal, Apple Pay.
transactions: purchases (merchant_raw as written, amount, date YYYY-MM-DD).
credits: statement credits posted (merchant, amount, date, offer_reference if named).
Use only facts in the email; leave unknown fields out. Empty lists when nothing applies."""

log = logging.getLogger(__name__)


def extract(s: Session, message_id: str, account: str, sender: str, subject: str,
            date: str, text: str) -> Classification | None:
    """Classify + extract one email (cached). None if it needs review."""
    if row := s.get(EmailProcessed, message_id):
        if row.status == "ok" and row.result_json:
            return Classification.model_validate_json(row.result_json)
        return None
    user = f"From: {sender}\nSubject: {subject}\nDate: {date}\n\n{text}"
    try:
        c = llm.complete_json(SYSTEM, user, Classification)
    except llm.LLMValidationError:
        log.warning("needs_review: %s", message_id)
        s.add(EmailProcessed(message_id=message_id, account=account, status="needs_review"))
        s.flush()
        return None
    for o in c.offers:
        o.source_message_id = message_id
    s.add(EmailProcessed(message_id=message_id, account=account, type=c.type, status="ok",
                         result_json=c.model_dump_json()))
    s.flush()
    return c
