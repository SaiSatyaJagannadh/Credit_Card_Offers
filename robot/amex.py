"""Amex Offers robot: log in, handle MFA, capture the offers JSON, parse it."""

import re
from datetime import UTC, date, datetime
from typing import Any

from app.config import card_by_id
from robot.base import BaseBankRobot, RobotOffer, credentials, log, parse_offer_text, pause

# ponytail: selectors and URL patterns are best guesses — tune against the live site
# (run `python -m robot.runner --once --bank amex --headed` and watch).
LOGIN_URL = "https://www.americanexpress.com/en-us/account/login"
USER_SEL = "#eliloUserID, input[name='UserID']"
PASS_SEL = "#eliloPassword, input[name='Password']"
SUBMIT_SEL = "#loginSubmit, button[type='submit']"
MFA_METHOD_SEL = "[data-testid*='otp'] button, button:has-text('Text'), button:has-text('Email')"
MFA_CODE_SEL = "input[autocomplete='one-time-code'], #question-value, input[name*='otp' i]"
OFFERS_JSON_RE = re.compile(r"americanexpress\.com/.*offer", re.I)
OFFER_CARD_SEL = "[data-testid*='offer' i], [class*='offer-card' i]"  # DOM fallback only

_MERCHANT_KEYS = ("merchantname", "merchant", "name", "title", "brandname")
_TEXT_KEYS = ("shortdescription", "description", "offerdescription", "headline", "title")
_EXPIRY_KEYS = ("expirydate", "expirationdate", "expiration", "expiresat", "enddate", "expiry")
_ENROLLED = {"enrolled", "added", "active_enrolled", "saved"}


def _get(d: dict, keys: tuple[str, ...]) -> Any:
    norm = {k.lower().replace("_", ""): v for k, v in d.items()}
    for k in keys:
        v = norm.get(k)
        if isinstance(v, dict):  # e.g. merchant: {name: ...}
            v = _get(v, ("name", "displayname"))
        if v not in (None, ""):
            return v
    return None


def _date(v: Any) -> date | None:
    if isinstance(v, int | float):  # epoch seconds or ms
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, UTC).date()
    if isinstance(v, str):
        if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", v):
            return date(*map(int, m.groups()))
        if m := re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", v):
            mo, d, y = map(int, m.groups())
            return date(y + 2000 if y < 100 else y, mo, d)
    return None


def _offer(d: dict) -> RobotOffer | None:
    merchant = _get(d, _MERCHANT_KEYS)
    text = _get(d, _TEXT_KEYS)
    if not isinstance(merchant, str) or not isinstance(text, str) or merchant == text:
        return None
    parsed = parse_offer_text(text)
    if not parsed:
        return None
    status = str(_get(d, ("status", "enrollmentstatus", "state")) or "").lower()
    enrolled = bool(_get(d, ("enrolled", "isenrolled", "added"))) or status in _ENROLLED
    terms = _get(d, ("terms", "longdescription", "exclusions"))
    oid = _get(d, ("offerid", "id"))
    return RobotOffer(merchant=merchant.strip(), offer_text=text.strip(),
                      expires_on=_date(_get(d, _EXPIRY_KEYS)), enrolled=enrolled,
                      exclusions=terms if isinstance(terms, str) else "",
                      source_message_id=f"amex:{oid}" if oid else None, **parsed)


def parse_amex_offers(payload: Any) -> list[RobotOffer]:
    """Walk any JSON shape; every dict that looks like an offer becomes a RobotOffer."""
    out: list[RobotOffer] = []
    if isinstance(payload, list):
        for x in payload:
            out += parse_amex_offers(x)
    elif isinstance(payload, dict):
        if o := _offer(payload):
            return [o]
        for v in payload.values():
            out += parse_amex_offers(v)
    return out


def parse_offer_card_text(text: str) -> RobotOffer | None:
    """DOM fallback: first line merchant, then the offer line, maybe 'Expires 10/31/26'."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) < 2:
        return None
    exp = next((x for x in lines if "expire" in x.lower()), None)
    return _offer({"merchant": lines[0], "description": lines[1], "expiry": exp,
                   "status": "added" if any(x.lower() == "added" for x in lines) else ""})


class AmexRobot(BaseBankRobot):
    bank = "amex"
    card_id = "amex_bce"
    json_url_re = OFFERS_JSON_RE

    def login(self) -> None:
        p = self.page
        p.goto(card_by_id(self.card_id)["offers_url"])  # trusted profile may skip login
        p.wait_for_load_state("networkidle")
        if not p.locator(USER_SEL).first.is_visible():
            return
        user, pw = credentials(self.bank)
        pause()
        self.type_slowly(USER_SEL, user)
        pause()
        self.type_slowly(PASS_SEL, pw)
        pause()
        p.locator(SUBMIT_SEL).first.click()
        p.wait_for_load_state("networkidle")
        pause()

    def needs_mfa(self) -> bool:
        p = self.page
        if p.locator(MFA_CODE_SEL).first.is_visible():
            return True
        method = p.locator(MFA_METHOD_SEL).first
        if method.is_visible():  # "how should we send your code?" step
            method.click()
            p.wait_for_load_state("networkidle")
            pause()
            return p.locator(MFA_CODE_SEL).first.is_visible()
        return False

    def submit_mfa(self, code: str) -> None:
        pause()
        self.type_slowly(MFA_CODE_SEL, code)
        self.page.keyboard.press("Enter")
        self.page.wait_for_load_state("networkidle")
        pause()

    def fetch_offers(self) -> list[RobotOffer]:
        p = self.page
        url = card_by_id(self.card_id)["offers_url"]
        if not p.url.startswith(url):
            p.goto(url)
        p.wait_for_load_state("networkidle")
        pause()
        p.mouse.wheel(0, 4000)  # lazy-loaded lists
        pause()
        p.wait_for_load_state("networkidle")
        offers = [o for _, data in self.captured for o in parse_amex_offers(data)]
        if not offers:
            log.warning("amex: no offers in captured JSON, falling back to DOM")
            cards = p.locator(OFFER_CARD_SEL).all_inner_texts()
            offers = [o for t in cards if (o := parse_offer_card_text(t))]
        return list({(o.merchant, o.offer_text, o.expires_on): o for o in offers}.values())
