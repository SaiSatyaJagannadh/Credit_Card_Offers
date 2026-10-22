"""Save a bank login to the OS keychain, then optionally log in once to trust this device.

    python -m robot.setup amex
"""

import argparse
import getpass

from app.config import card_by_id
from robot.base import KEYRING_SERVICE, profile_dir
from robot.runner import BANKS


def save_credentials(bank: str) -> None:
    import keyring

    user = input(f"{bank} username: ").strip()
    pw = getpass.getpass(f"{bank} password (not shown): ")
    if not user or not pw:
        raise SystemExit("Username and password are required; nothing saved.")
    keyring.set_password(KEYRING_SERVICE, f"{bank}:username", user)
    keyring.set_password(KEYRING_SERVICE, f"{bank}:password", pw)
    print(f"Saved {bank} login to the keychain (service '{KEYRING_SERVICE}').")


def trust_device(bank: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(profile_dir(bank)), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(card_by_id(BANKS[bank].card_id)["offers_url"])
        input("Log in, tick 'remember this device', then press Enter here to close... ")
        ctx.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m robot.setup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bank", choices=list(BANKS))
    ap.add_argument("--browser", action=argparse.BooleanOptionalAction, default=None,
                    help="open the browser profile to log in once (asks if omitted)")
    args = ap.parse_args(argv)
    save_credentials(args.bank)
    browser = args.browser
    if browser is None:
        browser = input("Open the browser now to log in once and trust it? [y/N] ")\
            .strip().lower() == "y"
    if browser:
        trust_device(args.bank)


if __name__ == "__main__":
    main()
