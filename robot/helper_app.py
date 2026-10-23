"""Card Offers helper: runs only on this Mac (127.0.0.1). Save bank logins to the Keychain,
test a sync, enter a security code, and turn on the daily automatic sync.

Open it by double-clicking "Card Offers Helper.command" in the project folder.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app import db, refresh  # noqa: E402
from app.ui import components as c  # noqa: E402
from app.ui import theme  # noqa: E402
from robot import schedule  # noqa: E402
from robot.base import KEYRING_SERVICE, has_credentials  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BANKS = {"amex": "American Express", "bofa": "Bank of America", "wellsfargo": "Wells Fargo"}

st.set_page_config(page_title="Card Offers helper", layout="centered")
theme.inject()


def save_login(bank: str, user: str, pw: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, f"{bank}:username", user)
    keyring.set_password(KEYRING_SERVICE, f"{bank}:password", pw)


def remove_login(bank: str) -> None:
    import keyring

    for k in ("username", "password"):
        try:
            keyring.delete_password(KEYRING_SERVICE, f"{bank}:{k}")
        except keyring.errors.PasswordDeleteError:
            pass


def start_sync(bank: str) -> None:
    log = Path.home() / "Library" / "Logs" / f"card-offers-{bank}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([sys.executable, "-m", "robot.runner", "--once", "--bank", bank,
                      "--headed"], cwd=ROOT, stdout=log.open("a"), stderr=subprocess.STDOUT)


st.title("Card Offers helper")
st.write("This page runs only on your Mac. Your bank logins are saved in your Mac's "
         "Keychain. They never go to the cloud app, the database or GitHub.")

try:
    with db.session() as s:
        statuses = refresh.source_status(s)
        runs = {b: db.latest_sync(s, b) for b in BANKS}
except Exception as e:  # noqa: BLE001
    st.error(f"Can't reach your database ({type(e).__name__}). Check DATABASE_URL in "
             ".streamlit/secrets.toml in the project folder.")
    st.stop()

st.subheader("Connect your banks")
for bank, name in BANKS.items():
    saved = has_credentials(bank)
    run = runs[bank]
    with st.container(border=True, key=f"card-{bank}"):
        a, b = st.columns([3, 2], vertical_alignment="center")
        a.markdown(f"**{name}**")
        label, tone = statuses[bank]
        b.html(c.pill("Login saved", "green") if saved else c.pill("Not connected", "gray"))
        if run:
            st.caption(c.md(f"Last sync: {label.split(': ', 1)[-1]}"
                            + (f" · {run.message[:160]}" if run.message else "")))
        if run and run.status == "needs_code":
            c.mfa_box(bank, name)
        if not saved:
            with st.form(f"login-{bank}", clear_on_submit=True):
                user = st.text_input(f"{name} username", autocomplete="username")
                pw = st.text_input(f"{name} password", type="password",
                                   autocomplete="current-password")
                if st.form_submit_button("Save login", type="primary"):
                    if not user.strip() or not pw:
                        st.error("Enter both your username and password.")
                    else:
                        save_login(bank, user.strip(), pw)
                        st.toast(f"{name} login saved to your Keychain.")
                        st.rerun()
        else:
            x, y = st.columns(2)
            if x.button("Sync now", key=f"sync-{bank}", type="primary", width="stretch",
                        help="Opens a browser window and logs in as you"):
                start_sync(bank)
                st.info(f"A browser window is opening for {name}. If the bank asks for a "
                        "security code, enter it on this page when it appears. Click "
                        "Check status to see progress.")
            if y.button("Remove login", key=f"rm-{bank}", width="stretch"):
                remove_login(bank)
                st.rerun()

st.button("Check status", width="stretch")

st.subheader("Automatic sync")
with st.container(border=True, key="card-schedule"):
    if schedule.is_on():
        st.html(c.pill("On", "green"))
        st.write("Your Mac syncs every connected bank at 7 AM and whenever you press "
                 "Refresh now in the app. Your Mac needs to be on and logged in.")
        if st.button("Turn off automatic sync", width="stretch"):
            schedule.turn_off()
            st.rerun()
    else:
        st.html(c.pill("Off", "gray"))
        st.write("Turn this on after a successful Sync now. Your Mac will then sync every "
                 "day at 7 AM and when you press Refresh now in the app.")
        if st.button("Turn on automatic sync", type="primary", width="stretch"):
            try:
                schedule.turn_on()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't turn it on: {e}")
