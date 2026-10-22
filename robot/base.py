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
from datetime import date
from pathlib import Path
from typing import Any

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
    if m := re.search(_MONEY + r"\s+(?:back|statement credit|credit)", t, re.I) \
            or re.search(r"(?:get|earn|receive)\s+(?:a\s+)?(?:one-time\s+)?" + _MONEY, t, re.I):
        return out | {"type": "fixed", "fixed_amount": _num(m.group(1))}
    # ponytail: "N points per dollar, up to M" lands as M points; per-dollar math if it matters
    pts = re.findall(r"([\d,]+)\s+(?:membership rewards\s*(?:®\s*)?)?(?:bonus\s+)?(?:points|pts)",
                     t, re.I)
    if pts:
        return out | {"type": "points", "fixed_amount": max(_num(p) for p in pts)}
    return None


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
