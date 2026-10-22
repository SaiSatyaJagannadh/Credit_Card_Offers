from datetime import UTC, date, datetime, timedelta

import pytest

from app import db
from app.config import settings_config
from workers import alerts

TOGGLES = [k for k, v in settings_config()["alert_defaults"].items() if isinstance(v, bool)]


@pytest.fixture
def outbox(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL", "me@example.com")
    db.set_engine("sqlite:///:memory:")
    with db.session() as s:
        db.sync_cards(s)
    sent: list[dict] = []
    return sent


def send_to(outbox):
    return lambda to, subject, html, text: outbox.append(
        dict(to=to, subject=subject, html=html, text=text))


def only(s, **flags):
    db.set_setting(s, "alerts", {k: False for k in TOGGLES} | flags)


def offer(s, merchant, expires, **kw):
    o = db.Offer(dedupe_key=f"{merchant}{expires}", issuer="Bank of America", card_id="bofa_ccr",
                 merchant_name=merchant, offer_text=kw.pop("text", "15% back, up to $20"),
                 type="pct", pct=15, max_credit=20, expires_on=expires, source="email", **kw)
    s.add(o)
    s.flush()
    return o


def ny(y, m, d, h):  # a New York wall-clock time as UTC
    from app.config import tz

    return datetime(y, m, d, h, tzinfo=tz()).astimezone(UTC)


@pytest.mark.parametrize("y,m,d,utc_8am", [(2026, 1, 15, 13), (2026, 7, 15, 12)])  # EST, EDT
def test_digest_only_at_8am_new_york(outbox, y, m, d, utc_8am):
    with db.session() as s:
        only(s, expiry_3day=True)
        offer(s, "Groupon", date(y, m, d) + timedelta(days=3))
        for h in (utc_8am - 1, utc_8am + 1):  # 7 AM and 9 AM local
            assert alerts.check(s, datetime(y, m, d, h, 5, tzinfo=UTC), send_to(outbox)) == []
        alerts.check(s, datetime(y, m, d, utc_8am, 5, tzinfo=UTC), send_to(outbox))
    assert len(outbox) == 1
    assert outbox[0]["subject"] == "Groupon offer expires in 3 days: $20 back unused"


def test_3day_and_1day_bundled_once(outbox):
    on = date(2026, 10, 22)
    with db.session() as s:
        only(s, expiry_3day=True)
        offer(s, "Groupon", on + timedelta(days=3))
        offer(s, "Lyft", on + timedelta(days=1), enrolled=True)
        offer(s, "Dell", on + timedelta(days=2))  # not due: only in "also expiring"
        offer(s, "Used", on + timedelta(days=1), status="used")  # already used: skipped
        now = ny(2026, 10, 22, 8)
        alerts.check(s, now, send_to(outbox))
        alerts.check(s, now + timedelta(minutes=30), send_to(outbox))  # rerun: dedupe
    assert len(outbox) == 1
    e = outbox[0]
    assert e["subject"].startswith("Lyft offer expires tomorrow: $20 back added")
    assert "Groupon" in e["text"] and "Dell" in e["text"] and "Used" not in e["text"]
    assert "Also expiring soon" in e["html"] and "calendar.google.com" in e["html"]
    assert "dates=20261023%2F20261024" in e["html"]


def test_quiet_hours_hold_then_send(outbox):
    with db.session() as s:
        only(s, new_high_value=True, mfa_needed=True)
        o = offer(s, "Hilton", date(2026, 12, 1))
        o.first_seen_at = datetime(2026, 10, 22, 3)
        s.add(db.SyncRun(source="bofa", status="needs_code"))
        s.flush()
        sent = alerts.check(s, ny(2026, 10, 21, 23), send_to(outbox))
        assert sent == ["Bank needs a security code"]  # MFA is immediate
        assert alerts.check(s, ny(2026, 10, 22, 6), send_to(outbox)) == []
        assert alerts.check(s, ny(2026, 10, 22, 7), send_to(outbox)) == ["New high-value offer"]
        assert alerts.check(s, ny(2026, 10, 22, 8), send_to(outbox)) == []
        assert s.query(db.AlertSent).count() == 2


def test_values_escaped_in_email(outbox):
    on = date(2026, 10, 22)
    with db.session() as s:
        only(s, expiry_3day=True)
        offer(s, '<script>alert("x")</script> & Co', on + timedelta(days=3),
              text='<img src=x onerror=alert(1)>')
        alerts.check(s, ny(2026, 10, 22, 8), send_to(outbox))
    h = outbox[0]["html"]
    assert "<script>" not in h and "<img" not in h
    assert "&lt;script&gt;" in h and "&amp; Co" in h
