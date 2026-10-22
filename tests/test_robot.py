import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.db import MfaCode, RefreshRequest, SyncRun, session, set_engine, utcnow
from robot import mfa, runner
from robot.amex import parse_amex_offers, parse_offer_card_text
from robot.base import parse_offer_text

FIXTURE = Path(__file__).parent / "fixtures" / "amex_offers.json"


@pytest.mark.parametrize("text,expected", [
    ("Spend $300 or more, get $60 back",
     dict(type="fixed", fixed_amount=60, min_spend=300, pct=None, max_credit=None)),
    ("Earn 20% back, up to a total of $10",
     dict(type="pct", pct=20, max_credit=10, min_spend=None, fixed_amount=None)),
    ("Get $5 back on a single purchase of $25+", dict(type="fixed", fixed_amount=5, min_spend=25)),
    ("Spend $50 or more, get 10% back up to $1,000",
     dict(type="pct", pct=10, min_spend=50, max_credit=1000)),
    ("Spend $250+, earn 5,000 Membership Rewards points",
     dict(type="points", fixed_amount=5000, min_spend=250)),
    ("Shop now and enjoy", None),
])
def test_parse_offer_text(text, expected):
    got = parse_offer_text(text)
    if expected is None:
        assert got is None
    else:
        assert {k: got[k] for k in expected} == expected


def test_parse_amex_offers_fixture():
    offers = {o.merchant: o for o in parse_amex_offers(json.loads(FIXTURE.read_text()))}
    assert set(offers) == {"Dell Technologies", "Under Armour", "Hilton"}
    dell, ua, hilton = offers["Dell Technologies"], offers["Under Armour"], offers["Hilton"]
    assert (dell.type, dell.fixed_amount, dell.min_spend) == ("fixed", 60, 300)
    assert dell.expires_on == date(2026, 10, 31) and not dell.enrolled
    assert dell.exclusions == "Online only at dell.com." and dell.source_message_id == "amex:A1"
    assert (ua.type, ua.pct, ua.max_credit, ua.enrolled) == ("pct", 20, 10, True)
    assert ua.expires_on == date(2026, 11, 8)
    assert hilton.type == "points" and hilton.fixed_amount == 5000
    assert hilton.expires_on == datetime.fromtimestamp(1798675200, UTC).date()


def test_parse_offer_card_text_dom_fallback():
    o = parse_offer_card_text("Lyft\nEarn 10% back, up to a total of $15\nExpires 12/1/26\nAdded")
    assert (o.merchant, o.pct, o.max_credit, o.expires_on, o.enrolled) == (
        "Lyft", 10, 15, date(2026, 12, 1), True)


@pytest.fixture
def db(monkeypatch):
    set_engine("sqlite:///:memory:")
    monkeypatch.setattr(mfa, "_notify", lambda source: None)
    with session() as s:
        run = SyncRun(source="amex")
        s.add(run)
        s.flush()
        return run.id


def _run(run_id):
    with session() as s:
        return s.get(SyncRun, run_id)


def test_mfa_code_used_and_deleted(db):
    sleeps = []

    def fake_sleep(sec):  # code arrives after the first poll
        sleeps.append(sec)
        with session() as s:
            s.add(MfaCode(source="amex", code="123456"))

    assert mfa.wait_for_code(db, "amex", timeout=30, sleep=fake_sleep) == "123456"
    assert sleeps == [5]
    with session() as s:
        assert s.query(MfaCode).count() == 0
    assert _run(db).status == "running"


def test_mfa_expired_code_ignored_then_timeout(db):
    with session() as s:
        s.add(MfaCode(source="amex", code="old", created_at=utcnow() - timedelta(minutes=11)))
        s.add(MfaCode(source="bofa", code="other"))  # another bank's code is not ours
    sleeps = []
    assert mfa.wait_for_code(db, "amex", timeout=20, sleep=sleeps.append) is None
    assert sleeps == [5, 5, 5, 5]
    run = _run(db)
    assert (run.status, run.message) == ("error", mfa.TIMEOUT_MSG)
    assert run.finished_at is not None


def test_mfa_sets_needs_code_while_waiting(db):
    seen = []
    mfa.wait_for_code(db, "amex", timeout=5, sleep=lambda _: seen.append(_run(db).status))
    assert seen == ["needs_code"]


def test_poll_once_coalesces_requests(db):
    with session() as s:
        s.add_all([RefreshRequest(source="all"), RefreshRequest(source="amex"),
                   RefreshRequest(source="gmail")])
    calls = []
    assert runner.poll_once(calls.append) == ["amex"]
    assert calls == [["amex"]]
    with session() as s:
        reqs = {r.source: r for r in s.query(RefreshRequest)}
    assert reqs["all"].done_at and reqs["amex"].picked_up_at
    assert reqs["gmail"].picked_up_at is None  # not the robot's job
    assert runner.poll_once(calls.append) == []


class FakeRobot(runner.BaseBankRobot):
    bank, card_id = "amex", "amex_bce"
    offers: list = []

    def __enter__(self):
        self.captured = [(7, {})]
        return self

    def __exit__(self, *exc):
        pass

    def login(self):
        pass

    def needs_mfa(self):
        return False

    def submit_mfa(self, code):
        pass

    def fetch_offers(self):
        return self.offers


def test_run_bank_saves_via_upsert_and_handles_errors(db, monkeypatch):
    import sys
    import types

    saved = []
    fake_match = types.ModuleType("workers.match")
    fake_match.upsert_offer = lambda s, issuer, card_id, o, source, ref: saved.append(
        (issuer, card_id, o.merchant, o.card_last_digits, source, ref))
    monkeypatch.setitem(sys.modules, "workers.match", fake_match)
    monkeypatch.setitem(runner.BANKS, "amex", FakeRobot)
    FakeRobot.offers = parse_amex_offers(json.loads(FIXTURE.read_text()))[:1]
    assert runner.run_bank("amex")
    assert saved == [("American Express", "amex_bce", "Dell Technologies", "92006", "robot",
                      "raw_payload:7")]
    with session() as s:
        assert s.query(SyncRun).order_by(SyncRun.id.desc()).first().status \
            == "ok"
    FakeRobot.offers = []
    assert not runner.run_bank("amex")
    assert not runner.run_bank("bofa")  # stub -> NotImplementedError recorded, no crash
    with session() as s:
        last = s.query(SyncRun).order_by(SyncRun.id.desc()).first()
    assert last.status == "error" and "Phase 5b" in last.message
