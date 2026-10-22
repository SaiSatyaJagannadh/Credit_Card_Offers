"""BankAmeriDeals robot (BofA Customized Cash Rewards): log in, MFA, capture deals JSON."""

import re
from typing import Any

from robot.base import RobotOffer, SelectorRobot, parse_offers

# ponytail: selectors and URL patterns are best guesses — tune against the live site
# (run `python -m robot.runner --once --bank bofa --headed` and watch).
USER_SEL = "#onlineId1, input[name='onlineId1'], input[name='onlineId']"
PASS_SEL = "#passcode1, input[name='passcode1'], input[type='password']"
SUBMIT_SEL = "#signIn, button:has-text('Log In'), button[type='submit']"
MFA_METHOD_SEL = "#btnARContinue, button:has-text('Text'), button:has-text('Send code')"
MFA_CODE_SEL = ("input[autocomplete='one-time-code'], #tlpvt-acw-authnum, "
                "input[name*='authcode' i], input[name*='otp' i]")
OFFERS_JSON_RE = re.compile(r"bankofamerica\.com/.*(deal|offer)", re.I)
DEALS_LINK_SEL = "a:has-text('BankAmeriDeals')"
OFFER_CARD_SEL = "[class*='deal-tile' i], [class*='deal-card' i], [data-testid*='deal' i]"


def parse_bofa_offers(payload: Any) -> list[RobotOffer]:
    """BankAmeriDeals: usually '15% cash back' with a separate max and expiry field."""
    return parse_offers(payload, "bofa")


class BofaRobot(SelectorRobot):
    bank = "bofa"
    card_id = "bofa_ccr"
    json_url_re = OFFERS_JSON_RE
    user_sel, pass_sel, submit_sel = USER_SEL, PASS_SEL, SUBMIT_SEL
    mfa_method_sel, mfa_code_sel, offer_card_sel = MFA_METHOD_SEL, MFA_CODE_SEL, OFFER_CARD_SEL
    deals_link_sel = DEALS_LINK_SEL
