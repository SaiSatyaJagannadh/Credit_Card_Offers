"""Wells Fargo Deals robot (Visa Signature): log in, MFA, capture deals JSON."""

import re
from typing import Any

from robot.base import RobotOffer, SelectorRobot, parse_offers

# ponytail: selectors and URL patterns are best guesses — tune against the live site
# (run `python -m robot.runner --once --bank wellsfargo --headed` and watch).
USER_SEL = "#j_username, input[name='j_username'], input[autocomplete='username']"
PASS_SEL = "#j_password, input[name='j_password'], input[type='password']"
SUBMIT_SEL = "button:has-text('Sign on'), button[type='submit']"
MFA_METHOD_SEL = "button:has-text('Text'), button:has-text('Mobile'), [data-testid*='otp'] button"
MFA_CODE_SEL = "input[autocomplete='one-time-code'], #otp, input[name*='otp' i]"
OFFERS_JSON_RE = re.compile(r"wellsfargo\.com/.*(deal|offer)", re.I)
DEALS_LINK_SEL = "a:has-text('Wells Fargo Deals'), a:has-text('My Wells Fargo Deals')"
OFFER_CARD_SEL = "[class*='deal' i][class*='card' i], [data-testid*='deal' i]"


def parse_wellsfargo_offers(payload: Any) -> list[RobotOffer]:
    """Wells Fargo Deals: usually 'Earn 10% cash back up to $15'."""
    return parse_offers(payload, "wellsfargo")


class WellsFargoRobot(SelectorRobot):
    bank = "wellsfargo"
    card_id = "wf_visa_sig"
    json_url_re = OFFERS_JSON_RE
    user_sel, pass_sel, submit_sel = USER_SEL, PASS_SEL, SUBMIT_SEL
    mfa_method_sel, mfa_code_sel, offer_card_sel = MFA_METHOD_SEL, MFA_CODE_SEL, OFFER_CARD_SEL
    deals_link_sel = DEALS_LINK_SEL
