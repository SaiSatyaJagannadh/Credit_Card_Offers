"""Wells Fargo offers robot — not built yet (brief: Amex first, then this)."""

from robot.base import BaseBankRobot, RobotOffer

MSG = "Wells Fargo robot not implemented yet — Phase 5b"


class WellsFargoRobot(BaseBankRobot):
    bank = "wellsfargo"
    card_id = "wf_visa_sig"

    def __enter__(self):
        raise NotImplementedError(MSG)

    def login(self) -> None:
        raise NotImplementedError(MSG)

    def needs_mfa(self) -> bool:
        raise NotImplementedError(MSG)

    def submit_mfa(self, code: str) -> None:
        raise NotImplementedError(MSG)

    def fetch_offers(self) -> list[RobotOffer]:
        raise NotImplementedError(MSG)
