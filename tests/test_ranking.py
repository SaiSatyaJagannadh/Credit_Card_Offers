from datetime import date
from types import SimpleNamespace

from app import ranking
from app.config import card_by_id

ON = date(2026, 10, 21)


def offer(**kw):
    base = dict(type="pct", pct=None, fixed_amount=None, min_spend=None, max_credit=None,
                status="active", expires_on=date(2026, 11, 30), enrolled=True, exclusions="",
                card_id="amex_bce", merchant_name="Uber")
    return SimpleNamespace(**{**base, **kw})


def test_offer_value_pct_capped():
    o = offer(pct=20, max_credit=10)
    assert ranking.offer_value(o, 40) == 8.0
    assert ranking.offer_value(o, 100) == 10.0


def test_offer_value_min_spend():
    o = offer(type="fixed", fixed_amount=60, min_spend=300)
    assert ranking.offer_value(o, 299.99) == 0
    assert ranking.offer_value(o, 300) == 60
    assert ranking.spend_for_full_credit(o) == 300
    assert ranking.spend_for_full_credit(offer(pct=15, max_credit=20)) == 133.33


def test_grades():
    assert ranking.grade(60) == "A"
    assert ranking.grade(15) == "B"
    assert ranking.grade(14.99) == "C"


def test_base_value_respects_cap():
    amex = card_by_id("amex_bce")
    v, r = ranking.base_value(amex, "groceries", 100, ON, {"amex_bce:amex_groceries": 5950})
    assert v == round(50 * 0.03 + 50 * 0.01, 2)
    assert r.note == "cap reached"


def test_bofa_choice_and_discover_activation():
    bofa = card_by_id("bofa_ccr")
    assert ranking.card_rate(bofa, "online", ON).rate == 0.03
    assert ranking.card_rate(bofa, "groceries", ON).rate == 0.02
    disc = card_by_id("discover_it")
    r = ranking.card_rate(disc, "online", ON)
    assert r.rate == 0.01 and "not activated" in r.note


def test_cap_usage_only_counts_current_period():
    used = ranking.cap_usage(
        [("bofa_ccr", "groceries", 100, date(2026, 10, 2)),
         ("bofa_ccr", "groceries", 100, date(2026, 9, 2)),  # last quarter
         ("bofa_ccr", "dining", 50, date(2026, 10, 3))],  # no cap
        ON)
    assert used == {"bofa_ccr:bofa_quarter": 100}


def test_rank_cards_offer_wins_and_breakdown():
    offers = [offer(card_id="wf_visa_sig", pct=20, max_credit=10)]
    opts = ranking.rank_cards(40, "other", offers, ON)
    assert opts[0].card_id == "wf_visa_sig"
    assert opts[0].total == 8.40
    assert opts[0].breakdown == "Offer 20% = $8.00 (cap $10) + base 1% = $0.40"


def test_rank_cards_ignores_expired():
    offers = [offer(card_id="wf_visa_sig", pct=20, max_credit=10, expires_on=date(2026, 10, 1))]
    assert ranking.rank_cards(40, "other", offers, ON)[0].card_id == "apple_card"


def test_amex_best_card_and_dedupe_key():
    assert ranking.amex_best_card(["amex_bce"], "groceries", ON) == "amex_bce"
    k1 = ranking.dedupe_key("American Express", "amex_bce", "Dell ", date(2026, 10, 31), "fixed:60")
    k2 = ranking.dedupe_key("american express", "amex_bce", "dell", date(2026, 10, 31), "fixed:60")
    assert k1 == k2


def test_quarter_label():
    assert ranking.quarter_label("2026Q4") == "Oct–Dec 2026"
