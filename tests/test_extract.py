import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import db, llm
from workers import extract
from workers.gmail_reader import html_to_text, is_bank

FIX = Path(__file__).parent / "fixtures"


class FakeLLM:
    """Stands in for the openai client: returns queued replies, records every request."""

    def __init__(self, *replies: str):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if not self.replies:
            raise AssertionError("unexpected LLM call")
        msg = SimpleNamespace(content=self.replies.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model")
    db.set_engine("sqlite:///:memory:")
    f = FakeLLM()
    llm.set_client(f)
    yield f
    llm.set_client(None)


OFFER_JSON = json.dumps({"type": "offer_new", "offers": [
    {"merchant": "Groupon", "offer_text": "15% back, up to $20", "type": "pct", "pct": 15,
     "max_credit": 20, "min_spend": 20, "expires_on": "2026-11-30", "card_last_digits": 92006,
     "channel": "online", "exclusions": ""},
    {"merchant": "Dell Technologies", "offer_text": "Spend $300, get $60", "type": "fixed",
     "fixed_amount": 60, "min_spend": 300, "expires_on": "2026-10-31"}]})


def _run(s, mid="m1"):
    text = html_to_text((FIX / "amex_offer.html").read_text())
    return extract.extract(s, mid, "me@x.com", "offers@americanexpress.com", "New offers",
                           "Wed, 21 Oct 2026", text)


def test_html_strip_and_truncate():
    text = html_to_text((FIX / "amex_offer.html").read_text())
    assert "Groupon" in text and "track()" not in text and "color:red" not in text
    assert "<" not in text and "  " not in text
    assert len(html_to_text((FIX / "amex_offer.html").read_text(), 50)) == 50


def test_is_bank():
    assert is_bank("Amex <alerts@welcome.americanexpress.com>")
    assert not is_bank("friend@gmail.com")
    assert not is_bank("phish@americanexpress.com.evil.io")


def test_valid_json(fake):
    fake.replies = [OFFER_JSON]
    with db.session() as s:
        c = _run(s)
        assert c.type == "offer_new" and len(c.offers) == 2
        assert c.offers[0].card_last_digits == "92006" and c.offers[0].pct == 15
        assert c.offers[1].source_message_id == "m1"
        row = s.get(db.EmailProcessed, "m1")
        assert row.status == "ok" and row.type == "offer_new"
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert fake.calls[0]["model"] == "test-model"


def test_retry_once_then_needs_review(fake):
    fake.replies = ["{not json", json.dumps({"type": "spam"})]
    with db.session() as s:
        assert _run(s) is None
        assert s.get(db.EmailProcessed, "m1").status == "needs_review"
    assert len(fake.calls) == 2
    assert "invalid" in fake.calls[1]["messages"][-1]["content"]
    with db.session() as s:  # never retried later either
        assert _run(s) is None
    assert len(fake.calls) == 2


def test_retry_succeeds(fake):
    fake.replies = ['{"type": "bogus"}', OFFER_JSON]
    with db.session() as s:
        assert len(_run(s).offers) == 2


def test_cache_hit_no_second_call(fake):
    fake.replies = [OFFER_JSON]
    with db.session() as s:
        first = _run(s)
    with db.session() as s:
        assert _run(s) == first
    assert len(fake.calls) == 1


def test_answer_question_passes_only_given_rows(fake):
    fake.replies = ["My data doesn't cover that."]
    out = llm.answer_question("best card at Costco?", {"offers": [{"merchant": "Lyft"}]})
    assert out == "My data doesn't cover that."
    system = fake.calls[0]["messages"][0]["content"]
    assert "Lyft" in system and "Never invent offers" in system
