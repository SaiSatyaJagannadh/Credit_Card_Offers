import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.db import MfaCode, RefreshRequest, SyncRun, session, set_engine, utcnow
from robot import mfa, runner
from robot.amex import parse_amex_offers
from robot.base import parse_offer_card_text, parse_offer_text
from robot.bofa import parse_bofa_offers
from robot.wellsfargo import parse_wellsfargo_offers

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "amex_offers.json"


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
    ("$5 cash back on a purchase of $25 or more",
     dict(type="fixed", fixed_amount=5, min_spend=25)),
    ("Earn 10% cash back up to $15", dict(type="pct", pct=10, max_credit=15, min_spend=None)),
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


def test_parse_bofa_offers_fixture():
    offers = {o.merchant: o for o in parse_bofa_offers(
        json.loads((FIXTURES / "bofa_offers.json").read_text()))}
    assert set(offers) == {"Uber Eats", "Home Depot"}
    ue, hd = offers["Uber Eats"], offers["Home Depot"]
    assert (ue.type, ue.pct, ue.max_credit, ue.enrolled) == ("pct", 15, 7.5, False)
    assert ue.expires_on == date(2026, 11, 14) and ue.source_message_id == "bofa:B1"
    assert (hd.type, hd.fixed_amount, hd.min_spend, hd.enrolled) == ("fixed", 10, 50, True)
    assert hd.expires_on == date(2026, 12, 1)


def test_parse_wellsfargo_offers_fixture():
    offers = {o.merchant: o for o in parse_wellsfargo_offers(
        json.loads((FIXTURES / "wellsfargo_offers.json").read_text()))}
    assert set(offers) == {"Lyft", "Chewy"}
    lyft, chewy = offers["Lyft"], offers["Chewy"]
    assert (lyft.type, lyft.pct, lyft.max_credit, lyft.enrolled) == ("pct", 10, 15, True)
    assert lyft.expires_on == date(2026, 11, 16)
    assert lyft.exclusions == "Lyft Pink membership excluded."
    assert lyft.source_message_id == "wellsfargo:W1"
    assert (chewy.type, chewy.fixed_amount, chewy.min_spend) == ("fixed", 8, 40)
    assert chewy.expires_on == datetime.fromtimestamp(1797465600, UTC).date()


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


def test_poll_once_coalesces_requests(db, monkeypatch):
    monkeypatch.setattr(runner, "connected_banks", lambda: ["amex", "bofa", "wellsfargo"])
    with session() as s:
        s.add_all([RefreshRequest(source="all"), RefreshRequest(source="amex"),
                   RefreshRequest(source="gmail")])
    calls = []
    assert runner.poll_once(calls.append) == ["amex", "bofa", "wellsfargo"]
    assert calls == [["amex", "bofa", "wellsfargo"]]
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
    with session() as s:
        last = s.query(SyncRun).order_by(SyncRun.id.desc()).first()
    assert last.status == "error" and "no offers found" in last.message


@pytest.mark.parametrize("bank,card_id,issuer,parse,fixture,merchant", [
    ("bofa", "bofa_ccr", "Bank of America", parse_bofa_offers, "bofa_offers.json", "Uber Eats"),
    ("wellsfargo", "wf_visa_sig", "Wells Fargo", parse_wellsfargo_offers,
     "wellsfargo_offers.json", "Lyft"),
])
def test_run_bank_bofa_wellsfargo(db, monkeypatch, bank, card_id, issuer, parse, fixture,
                                  merchant):
    import sys
    import types

    saved = []
    fake_match = types.ModuleType("workers.match")
    fake_match.upsert_offer = lambda s, iss, cid, o, source, ref: saved.append(
        (iss, cid, o.merchant, source, ref))
    monkeypatch.setitem(sys.modules, "workers.match", fake_match)
    offers = parse(json.loads((FIXTURES / fixture).read_text()))
    fake = type("Fake", (FakeRobot,), {"bank": bank, "card_id": card_id, "offers": offers})
    monkeypatch.setitem(runner.BANKS, bank, fake)
    assert runner.run_bank(bank)
    assert saved[0] == (issuer, card_id, merchant, "robot", "raw_payload:7")
    with session() as s:
        last = s.query(SyncRun).order_by(SyncRun.id.desc()).first()
    assert (last.source, last.status) == (bank, "ok")


def test_connected_banks_skips_banks_without_login(monkeypatch):
    import robot.base

    monkeypatch.setattr(robot.base, "has_credentials", lambda b: b == "amex")
    assert runner.connected_banks() == ["amex"]


def test_login_from_app_reaches_keychain_only(db, monkeypatch):
    import sys
    from types import SimpleNamespace

    from app import sealed
    from app.db import Setting, get_setting, set_setting

    store = {}
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(  # CI has no keyring
        get_password=lambda svc, k: store.get(k),
        set_password=lambda svc, k, v: store.__setitem__(k, v)))
    monkeypatch.setattr(runner, "connected_banks", lambda: [b for b in runner.DEFAULT_BANKS
                                                            if f"{b}:password" in store])
    priv = runner.link_app()
    assert runner.link_app() == priv  # key made once
    with session() as s:
        set_setting(s, sealed.pending_key("amex"),
                    sealed.seal(get_setting(s, sealed.PUBLIC_KEY), "me", "s3cret!"))
    with session() as s:  # the DB holds ciphertext only
        assert "s3cret" not in " ".join(r.value for r in s.query(Setting))
    assert runner.apply_pending_logins(priv) == ["amex"]
    assert store["amex:username"] == "me" and store["amex:password"] == "s3cret!"
    with session() as s:
        assert get_setting(s, sealed.pending_key("amex")) is None
        assert get_setting(s, sealed.SEEN)["banks"] == ["amex"]
    calls = []
    assert runner.poll_once(calls.append, ["amex"]) == ["amex"]  # syncs right away
