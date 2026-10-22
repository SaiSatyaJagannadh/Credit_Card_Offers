"""Amex Offers robot: log in, handle MFA, capture the offers JSON, parse it."""

import re
from typing import Any

from robot.base import RobotOffer, SelectorRobot, parse_offers

# ponytail: selectors and URL patterns are best guesses — tune against the live site
# (run `python -m robot.runner --once --bank amex --headed` and watch).
USER_SEL = "#eliloUserID, input[name='UserID']"
PASS_SEL = "#eliloPassword, input[name='Password']"
SUBMIT_SEL = "#loginSubmit, button[type='submit']"
MFA_METHOD_SEL = "[data-testid*='otp'] button, button:has-text('Text'), button:has-text('Email')"
MFA_CODE_SEL = "input[autocomplete='one-time-code'], #question-value, input[name*='otp' i]"
OFFERS_JSON_RE = re.compile(r"americanexpress\.com/.*offer", re.I)
OFFER_CARD_SEL = "[data-testid*='offer' i], [class*='offer-card' i]"  # DOM fallback only


def parse_amex_offers(payload: Any) -> list[RobotOffer]:
    return parse_offers(payload, "amex")


class AmexRobot(SelectorRobot):
    bank = "amex"
    card_id = "amex_bce"
    json_url_re = OFFERS_JSON_RE
    user_sel, pass_sel, submit_sel = USER_SEL, PASS_SEL, SUBMIT_SEL
    mfa_method_sel, mfa_code_sel, offer_card_sel = MFA_METHOD_SEL, MFA_CODE_SEL, OFFER_CARD_SEL
