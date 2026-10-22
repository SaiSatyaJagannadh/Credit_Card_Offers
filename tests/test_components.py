from datetime import timedelta
from types import SimpleNamespace

from app import db
from app.db import SyncRun, utcnow
from app.refresh import source_status
from app.ui.components import offer_row


def test_offer_row_escapes_merchant():
    o = SimpleNamespace(merchant_name="<script>alert(1)</script>", offer_text="<b>x</b>",
                        type="fixed", fixed_amount=60, pct=None, max_credit=None,
                        min_spend=300, expires_on=None, enrolled=False)
    card = {"name": "Blue Cash", "last_digits": "92006",
            "offers_url": "https://example.com/offers?a=1&b=2"}
    html = offer_row(o, card, utcnow().date(), new=True, shop_here=True)
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html
    assert "up to $60" in html and "New" in html and "You shop here" in html
    assert 'href="https://example.com/offers?a=1&amp;b=2"' in html


def test_source_status_labels():
    db.set_engine("sqlite:///:memory:")
    now = utcnow()
    with db.session() as s:
        s.add_all([
            SyncRun(source="gmail", started_at=now, status="running"),
            SyncRun(source="amex", started_at=now, finished_at=now, status="ok"),
            SyncRun(source="bofa", started_at=now, status="needs_code"),
            SyncRun(source="wellsfargo", started_at=now - timedelta(days=3),
                    finished_at=now - timedelta(days=3), status="ok"),
        ])
    with db.session() as s:
        st = source_status(s, now)
    assert st["gmail"] == ("Gmail: syncing…", "blue")
    assert st["amex"][0].startswith("Amex: synced ") and st["amex"][1] == "green"
    assert st["bofa"] == ("BofA: needs security code", "amber")
    assert st["wellsfargo"] == ("Wells Fargo: Last updated 3 days ago", "amber")
