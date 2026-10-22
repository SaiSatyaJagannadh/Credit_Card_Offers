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
