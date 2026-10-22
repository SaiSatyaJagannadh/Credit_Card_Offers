from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import db, llm
from tests.test_extract import FakeLLM
from workers import match
from workers.extract import Classification, CreditX, OfferX, TransactionX


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model")
    db.set_engine("sqlite:///:memory:")
    llm.set_client(FakeLLM())  # any LLM call fails the test
    with db.session() as s:
        db.sync_cards(s)
        s.add(db.Merchant(name="Under Armour", category="online"))
        s.add(db.Merchant(name="Groupon", category="online"))
        s.flush()
        yield s
    llm.set_client(None)


def test_fuzzy_alias_persisted(s):
    m = match.merchant_for(s, "UNDER  ARMOR")
    assert m.name == "Under Armour"
    assert s.scalar(select(db.MerchantAlias).where(db.MerchantAlias.alias == "under armor"))
    assert match.merchant_for(s, "under armor").id == m.id


def test_llm_fallback_maps_to_existing(s):
    llm.set_client(FakeLLM('{"existing": "Groupon", "name": "", "category": "online"}'))
    assert match.merchant_for(s, "GRPN*DEALS 8773").name == "Groupon"


def test_card_mapping():
    assert match.card_for("92006", "American Express") == "amex_bce"
    assert match.card_for("2006", None) == "amex_bce"
    assert match.card_for(None, "Wells Fargo") == "wf_visa_sig"
    assert match.issuer_for_sender("x@ealerts.bankofamerica.com") == "Bank of America"


def test_email_and_robot_same_offer_one_row(s):
    exp = date(2026, 11, 30)
    email = OfferX(merchant="Groupon", offer_text="15% back", type="pct", pct=15, max_credit=20,
                   expires_on=exp)
    a = match.upsert_offer(s, "American Express", "amex_bce", email, "email", "m1")
    first_seen = a.first_seen_at
    robot = SimpleNamespace(merchant="groupon", offer_text="Get 15% back", type="pct", pct=15.0,
                            fixed_amount=None, min_spend=None, max_credit=20.0, expires_on=exp,
                            channel="online", exclusions="", enrolled=True)
    b = match.upsert_offer(s, "American Express", "amex_bce", robot, "robot", "payload:1")
    assert a.id == b.id and len(s.scalars(select(db.Offer)).all()) == 1
    assert b.enrolled and b.first_seen_at == first_seen and b.last_seen_at >= first_seen


def test_apply_idempotent_and_expire(s):
    c = Classification(type="transaction_alert", transactions=[
        TransactionX(merchant_raw="GROUPON", amount=45, date=date(2026, 10, 20),
                     card_last_digits="92006")],
        credits=[CreditX(merchant="Groupon", amount=6.75, date=date(2026, 10, 22))])
    assert match.apply(s, "alerts@americanexpress.com", c, "m9")["transactions"] == 1
    assert match.apply(s, "alerts@americanexpress.com", c, "m9") == {
        "offers": 0, "transactions": 0, "credits": 0}
    o = OfferX(merchant="Groupon", type="fixed", fixed_amount=5, expires_on=date(2026, 1, 1))
    match.upsert_offer(s, "Bank of America", "bofa_ccr", o, "email", "m2")
    assert match.expire_offers(s, date(2026, 10, 22)) == 1
