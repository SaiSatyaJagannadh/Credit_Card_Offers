"""Run bank robots: `--once` (daily, from the OS scheduler) or `--poll` (refresh_requests).

Sequential, one login per bank per run. Failures keep the previous offers.
"""

import argparse
import logging
import time
from collections.abc import Callable

from sqlalchemy import select

from app.config import card_by_id
from app.db import RefreshRequest, SyncRun, session, sync_cards, utcnow
from robot import mfa
from robot.amex import AmexRobot
from robot.base import BaseBankRobot, RobotOffer
from robot.bofa import BofaRobot
from robot.wellsfargo import WellsFargoRobot

log = logging.getLogger("robot")

BANKS: dict[str, type[BaseBankRobot]] = {
    "amex": AmexRobot, "bofa": BofaRobot, "wellsfargo": WellsFargoRobot}
DEFAULT_BANKS = ["amex", "bofa", "wellsfargo"]  # sequential, one login each


def connected_banks() -> list[str]:
    """Default banks with a saved login: an unconnected bank isn't an error every run."""
    from robot.base import has_credentials

    return [b for b in DEFAULT_BANKS if has_credentials(b)]


POLL_SECONDS = 60


def link_app() -> str:
    """Publish this Mac's public key so the app can send it sealed logins (once)."""
    import keyring

    from app import sealed
    from app.db import get_setting, set_setting
    from robot.base import KEYRING_SERVICE

    priv = keyring.get_password(KEYRING_SERVICE, "app-link:private-key")
    with session() as s:
        if not priv or not get_setting(s, sealed.PUBLIC_KEY):
            priv, pub = sealed.new_keypair()
            keyring.set_password(KEYRING_SERVICE, "app-link:private-key", priv)
            set_setting(s, sealed.PUBLIC_KEY, pub)
    return priv


def apply_pending_logins(priv: str) -> list[str]:
    """Logins typed in the app -> Keychain; the sealed rows are deleted. Returns banks to
    sync. Also reports which banks have a login, so the app can show it."""
    import keyring

    from app import sealed
    from app.db import Setting, get_setting, set_setting
    from robot.base import KEYRING_SERVICE

    new = []
    with session() as s:
        for bank in BANKS:
            blob = get_setting(s, sealed.pending_key(bank))
            if blob is None:
                continue
            s.delete(s.get(Setting, sealed.pending_key(bank)))
            try:
                user, pw = sealed.unseal(priv, blob)
            except Exception:  # sealed for an older key: ask again in the app
                log.error("%s: could not open the login sent from the app", bank)
                continue
            keyring.set_password(KEYRING_SERVICE, f"{bank}:username", user)
            keyring.set_password(KEYRING_SERVICE, f"{bank}:password", pw)
            log.info("%s: login saved from the app", bank)
            new.append(bank)
        set_setting(s, sealed.SEEN, {"at": utcnow().isoformat(), "banks": connected_banks()})
    return new


def save_offers(robot: BaseBankRobot, offers: list[RobotOffer]) -> int:
    from workers.match import upsert_offer  # lazy: workers may not be importable everywhere

    card = card_by_id(robot.card_id)
    ref = f"raw_payload:{robot.captured[-1][0]}" if robot.captured else None
    with session() as s:
        sync_cards(s)
        for o in offers:
            o.card_last_digits = o.card_last_digits or str(card.get("last_digits") or "")
            upsert_offer(s, card["issuer"], robot.card_id, o, "robot", ref)
    return len(offers)


def run_bank(bank: str, headless: bool = True) -> bool:
    with session() as s:
        run = SyncRun(source=bank)
        s.add(run)
        s.flush()
        run_id = run.id
    log.info("%s: starting", bank)
    try:
        with BANKS[bank](headless=headless) as robot:
            robot.login()
            if robot.needs_mfa():
                code = mfa.wait_for_code(run_id, bank)
                if code is None:
                    return False  # status already set; old offers untouched
                robot.submit_mfa(code)
                if robot.needs_mfa():
                    raise RuntimeError("security code was not accepted")
            offers = robot.fetch_offers()
            if not offers:
                raise RuntimeError("no offers found — the page may have changed")
            n = save_offers(robot, offers)
    except Exception as e:  # message only: no page content, never credentials
        msg = f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}"
        log.error("%s: failed — %s", bank, msg)
        mfa.set_status(run_id, "error", msg + " — kept previous offers", done=True)
        return False
    mfa.set_status(run_id, "ok", f"{n} offers", done=True)
    log.info("%s: ok, %d offers", bank, n)
    return True


def run_banks(banks: list[str], headless: bool = True) -> None:
    for b in banks:
        run_bank(b, headless)


def poll_once(run: Callable[[list[str]], None] = run_banks,
              new_logins: list[str] | None = None) -> list[str]:
    """Pick up pending refresh requests, run each requested bank once, mark them done.
    Banks whose login just arrived from the app sync right away."""
    with session() as s:
        reqs = s.scalars(select(RefreshRequest).where(
            RefreshRequest.picked_up_at.is_(None),
            RefreshRequest.source.in_(["all", *BANKS]))).all()
        for r in reqs:
            r.picked_up_at = utcnow()
        ids = [r.id for r in reqs]
        banks: list[str] = list(new_logins or [])
        for r in reqs:
            for b in connected_banks() if r.source == "all" else [r.source]:
                if b not in banks:
                    banks.append(b)
    if not ids and not banks:
        return []
    try:
        run(banks)
    finally:
        with session() as s:
            for r in s.scalars(select(RefreshRequest).where(RefreshRequest.id.in_(ids))):
                r.done_at = utcnow()
    return banks


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m robot.runner", description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run once and exit (default)")
    mode.add_argument("--poll", action="store_true",
                      help=f"loop forever, checking refresh_requests every {POLL_SECONDS}s")
    ap.add_argument("--bank", action="append", choices=list(BANKS),
                    help=f"bank to run (repeatable; default: {', '.join(DEFAULT_BANKS)})")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    headless = not args.headed
    if not args.poll:
        run_banks(args.bank or connected_banks(), headless)
        return
    priv = None
    while True:
        try:
            priv = priv or link_app()
            poll_once(lambda banks: run_banks(banks, headless), apply_pending_logins(priv))
        except Exception as e:  # DB blip: keep polling
            log.error("poll failed: %s", type(e).__name__)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
