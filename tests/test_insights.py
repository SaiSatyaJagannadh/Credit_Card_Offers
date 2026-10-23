from app import db, insights
from app.demo import seed


def test_demo_seed_and_insights():
    db.set_engine("sqlite:///:memory:")
    with db.session() as s:
        seed(s)
        seed(s)  # idempotent
    with db.session() as s:
        k = insights.kpis(s)
        assert k.not_added_count == 5
        assert k.saved_this_year > 0
        assert any(o.merchant_name == "Groupon" for o in k.expiring_7)
        misses = insights.missed_savings(s, insights.today().replace(day=1).replace(
            month=1))
        lyft = [m for m in misses if m.merchant == "Lyft"]
        assert any(m.best.card_id == "wf_visa_sig" and m.missed == 4.5 for m in lyft)
        assert any(t.kind == "mfa" for t in insights.todos(s))
        dell = [p for p in insights.spend_progress(s) if p.offer.merchant_name == "Dell"]
        assert dell[0].target == 300
        opts = insights.best_for_purchase(s, "lyft", 40)
        assert opts[0].card_id == "wf_visa_sig"


def test_card_overrides_layer_over_yaml():
    from app import config, ranking
    from app.insights import today

    q = ranking.quarter_key(today())
    try:
        config.set_card_overrides({
            "bofa_ccr": {"last_digits": "1234", "choice_category": "gas"},
            "discover_it": {"rotating": {q: {"categories": ["gas"], "activated": True}}},
            "verizon_visa": {"categories": {"gas": {"rate": 0.04}}}})
        bofa = config.card_by_id("bofa_ccr")
        assert bofa["last_digits"] == "1234" and bofa["categories"]["groceries"]["rate"] == 0.02
        assert ranking.card_rate(bofa, "gas", today()).rate == 0.03
        assert ranking.card_rate(config.card_by_id("discover_it"), "gas", today()).rate == 0.05
        best = dict((cat, card["id"]) for cat, card, _ in ranking.best_card_per_category(today()))
        assert best["gas"] in ("discover_it", "verizon_visa")
    finally:
        config.set_card_overrides({})
    assert config.card_by_id("bofa_ccr")["last_digits"] == ""
