"""Shared bank-robot plumbing: offer shape, offer-text parsing, keyring, Playwright session.

Runs on the home machine only. Never log credentials or page content.
"""

import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.config import card_by_id
from app.db import RawPayload, session

log = logging.getLogger("robot")

KEYRING_SERVICE = "card-offers"
PROFILES_DIR = Path.home() / ".card-offers" / "profiles"  # outside the repo on purpose
MAX_PAYLOAD_CHARS = 1_000_000  # raw_payloads is for debugging, not an archive


@dataclass
class RobotOffer:
    """Attribute shape expected by workers.match.upsert_offer."""

    merchant: str
    offer_text: str
    type: str  # pct | fixed | points
    pct: float | None = None
    fixed_amount: float | None = None
    min_spend: float | None = None
    max_credit: float | None = None
    expires_on: date | None = None
    card_last_digits: str = ""
    channel: str = "both"
    exclusions: str = ""
    source_message_id: str | None = None
    enrolled: bool = False


_MONEY = r"\$\s?([\d,]+(?:\.\d{1,2})?)"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_offer_text(text: str) -> dict | None:
    """'Spend $300 or more, get $60 back' / 'Earn 20% back, up to a total of $10' /
    'Spend $50+, earn 2,000 points' -> type/pct/fixed_amount/min_spend/max_credit."""
    t = text.replace(" ", " ")
    m = re.search(r"(?:spend|purchase of|minimum (?:purchase )?of)\s+" + _MONEY, t, re.I) \
        or re.search(_MONEY + r"\s?(?:\+|or more)", t, re.I)
    out: dict[str, Any] = {"pct": None, "fixed_amount": None, "max_credit": None,
                           "min_spend": _num(m.group(1)) if m else None}
    if m := re.search(r"(\d+(?:\.\d+)?)\s?%", t):
        cap = re.search(r"up to (?:a total of )?" + _MONEY, t, re.I)
        return out | {"type": "pct", "pct": _num(m.group(1)),
                      "max_credit": _num(cap.group(1)) if cap else None}
    if m := re.search(_MONEY + r"\s+(?:(?:cash\s+)?back|statement credit|credit)", t, re.I) \
            or re.search(r"(?:get|earn|receive)\s+(?:a\s+)?(?:one-time\s+)?" + _MONEY, t, re.I):
        return out | {"type": "fixed", "fixed_amount": _num(m.group(1))}
    # ponytail: "N points per dollar, up to M" lands as M points; per-dollar math if it matters
    pts = re.findall(r"([\d,]+)\s+(?:membership rewards\s*(?:®\s*)?)?(?:bonus\s+)?(?:points|pts)",
                     t, re.I)
    if pts:
        return out | {"type": "points", "fixed_amount": max(_num(p) for p in pts)}
    return None


# Generic JSON offer walk, shared by every bank. Keys are compared lowercased, "_" removed.
_MERCHANT_KEYS = ("merchantname", "merchant", "name", "title", "brandname")
_TEXT_KEYS = ("shortdescription", "description", "offerdescription", "dealdescription",
              "headline", "offerheadline", "offertext", "offertitle", "title")
_EXPIRY_KEYS = ("expirydate", "expirationdate", "expiration", "expiresat", "enddate", "expiry",
                "expireson", "validuntil")
_MAX_KEYS = ("maxreward", "maxcashback", "maxcredit", "maxsavings", "maxamount")
_ENROLLED = {"enrolled", "added", "active_enrolled", "saved", "activated"}


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


def offer_from_dict(d: dict, bank: str) -> RobotOffer | None:
    merchant = _get(d, _MERCHANT_KEYS)
    text = _get(d, _TEXT_KEYS)
    if not isinstance(merchant, str) or not isinstance(text, str) or merchant == text:
        return None
    parsed = parse_offer_text(text)
    if not parsed:
        return None
    if parsed["max_credit"] is None and parsed["type"] == "pct":  # "15% cash back" + max field
        cap = _get(d, _MAX_KEYS)
        if isinstance(cap, str) and (m := re.search(r"[\d,]+(?:\.\d+)?", cap)):
            cap = _num(m.group())
        parsed["max_credit"] = float(cap) if isinstance(cap, int | float) else None
    status = str(_get(d, ("status", "enrollmentstatus", "state")) or "").lower()
    enrolled = bool(_get(d, ("enrolled", "isenrolled", "added", "activated", "isactivated"))) \
        or status in _ENROLLED
    terms = _get(d, ("terms", "longdescription", "exclusions"))
    oid = _get(d, ("offerid", "dealid", "id"))
    return RobotOffer(merchant=merchant.strip(), offer_text=text.strip(),
                      expires_on=_date(_get(d, _EXPIRY_KEYS)), enrolled=enrolled,
                      exclusions=terms if isinstance(terms, str) else "",
                      source_message_id=f"{bank}:{oid}" if oid else None, **parsed)


def parse_offers(payload: Any, bank: str) -> list[RobotOffer]:
    """Walk any JSON shape; every dict that looks like an offer becomes a RobotOffer."""
    out: list[RobotOffer] = []
    if isinstance(payload, list):
        for x in payload:
            out += parse_offers(x, bank)
    elif isinstance(payload, dict):
        if o := offer_from_dict(payload, bank):
            return [o]
        for v in payload.values():
            out += parse_offers(v, bank)
    return out


def parse_offer_card_text(text: str) -> RobotOffer | None:
    """DOM fallback: first line merchant, then the offer line, maybe 'Expires 10/31/26'."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) < 2:
        return None
    exp = next((x for x in lines if re.search(r"\bexpire|\bends\b", x, re.I)), None)
    status = next((x for x in lines if x.lower() in _ENROLLED), "")
    return offer_from_dict({"merchant": lines[0], "description": lines[1], "expiry": exp,
                            "status": status}, "dom")


def pause(lo: float = 1.0, hi: float = 3.0) -> None:
    """Human-paced delay between steps."""
    time.sleep(random.uniform(lo, hi))


def credentials(bank: str) -> tuple[str, str]:
    import keyring

    user = keyring.get_password(KEYRING_SERVICE, f"{bank}:username")
    pw = keyring.get_password(KEYRING_SERVICE, f"{bank}:password")
    if not user or not pw:
        raise RuntimeError(f"No saved login for {bank} — run: python -m robot.setup {bank}")
    return user, pw


def profile_dir(bank: str) -> Path:
    p = PROFILES_DIR / bank
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def truncate(text: str) -> str:
    if len(text) <= MAX_PAYLOAD_CHARS:
        return text
    return text[:MAX_PAYLOAD_CHARS] + f"\n...[truncated, {len(text)} chars total]"


class BaseBankRobot(ABC):
    """One logged-in browser session per bank per run. Use as a context manager."""

    bank: str  # sync_runs.source: amex | bofa | wellsfargo
    card_id: str  # cards.yaml id
    json_url_re: re.Pattern = re.compile(r"$^")  # responses to capture into raw_payloads

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.captured: list[tuple[int, Any]] = []  # (raw_payload id, parsed JSON)
        self.page: Any = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(profile_dir(self.bank)), headless=self.headless)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.on("response", self._on_response)
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    def _on_response(self, resp: Any) -> None:
        if not self.json_url_re.search(resp.url):
            return
        if "json" not in (resp.headers.get("content-type") or ""):
            return
        try:
            data = resp.json()
        except Exception:
            return
        with session() as s:
            row = RawPayload(source=self.bank, url=resp.url.split("?")[0][:2000],
                             payload=truncate(json.dumps(data)))
            s.add(row)
            s.flush()
            self.captured.append((row.id, data))
        log.info("%s: captured JSON payload %s", self.bank, row.id)

    def type_slowly(self, selector: str, text: str) -> None:
        loc = self.page.locator(selector).first
        loc.click()
        loc.press_sequentially(text, delay=random.randint(60, 140))

    @abstractmethod
    def login(self) -> None: ...

    @abstractmethod
    def needs_mfa(self) -> bool: ...

    @abstractmethod
    def submit_mfa(self, code: str) -> None: ...

    @abstractmethod
    def fetch_offers(self) -> list[RobotOffer]: ...


class SelectorRobot(BaseBankRobot):
    """Login / MFA / fetch driven by per-bank selectors. Subclasses only set class attributes."""

    user_sel = pass_sel = submit_sel = mfa_method_sel = mfa_code_sel = offer_card_sel = ""
    deals_link_sel = ""  # clicked if the offers page needs one more hop (WF Deals)
    offers_url = ""  # default: cards.yaml offers_url

    def _offers_url(self) -> str:
        return self.offers_url or card_by_id(self.card_id)["offers_url"]

    def login(self) -> None:
        p = self.page
        p.goto(self._offers_url())  # trusted profile may skip login
        p.wait_for_load_state("networkidle")
        if not p.locator(self.user_sel).first.is_visible():
            return
        user, pw = credentials(self.bank)
        pause()
        self.type_slowly(self.user_sel, user)
        pause()
        self.type_slowly(self.pass_sel, pw)
        pause()
        p.locator(self.submit_sel).first.click()
        p.wait_for_load_state("networkidle")
        pause()

    def needs_mfa(self) -> bool:
        p = self.page
        if p.locator(self.mfa_code_sel).first.is_visible():
            return True
        method = p.locator(self.mfa_method_sel).first
        if method.is_visible():  # "how should we send your code?" step
            method.click()
            p.wait_for_load_state("networkidle")
            pause()
            return p.locator(self.mfa_code_sel).first.is_visible()
        return False

    def submit_mfa(self, code: str) -> None:
        pause()
        self.type_slowly(self.mfa_code_sel, code)
        self.page.keyboard.press("Enter")
        self.page.wait_for_load_state("networkidle")
        pause()

    def fetch_offers(self) -> list[RobotOffer]:
        p = self.page
        url = self._offers_url()
        if not p.url.startswith(url):
            p.goto(url)
        p.wait_for_load_state("networkidle")
        if self.deals_link_sel and (link := p.locator(self.deals_link_sel).first).is_visible():
            link.click()
            p.wait_for_load_state("networkidle")
        pause()
        p.mouse.wheel(0, 4000)  # lazy-loaded lists
        pause()
        p.wait_for_load_state("networkidle")
        offers = [o for _, data in self.captured for o in parse_offers(data, self.bank)]
        if not offers:
            log.warning("%s: no offers in captured JSON, falling back to DOM", self.bank)
            cards = p.locator(self.offer_card_sel).all_inner_texts()
            offers = [o for t in cards if (o := parse_offer_card_text(t))]
        return list({(o.merchant, o.offer_text, o.expires_on): o for o in offers}.values())
