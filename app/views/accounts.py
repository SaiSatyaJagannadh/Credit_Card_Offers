"""Accounts: connect banks (login sealed for the Mac), sync now, MFA codes, Gmail status."""

from datetime import datetime, timedelta

import streamlit as st

from app import db, refresh, sealed
from app.config import cards_config
from app.ui import components as c

with db.session() as s:
    statuses = refresh.source_status(s)
    runs = {src: db.latest_sync(s, src) for src in refresh.SOURCES}
    public_key = db.get_setting(s, sealed.PUBLIC_KEY)
    seen = db.get_setting(s, sealed.SEEN) or {}
    pending = {b for b in refresh.BANKS if db.get_setting(s, sealed.pending_key(b))}

seen_at = datetime.fromisoformat(seen["at"]) if seen.get("at") else None
mac_online = bool(seen_at and seen_at > db.utcnow() - timedelta(minutes=3))
saved = set(seen.get("banks", []))


def connect(bank: str, user: str, pw: str) -> None:
    blob = sealed.seal(public_key, user, pw)  # only the Mac can open this
    with db.session() as s:
        db.set_setting(s, sealed.pending_key(bank), blob)


def sync(bank: str) -> None:
    with db.session() as s:
        s.add(db.RefreshRequest(source=bank))


st.title("Accounts")
st.caption("Connect your banks here. Your Mac does the actual bank login, so your "
           "password is locked with a key only your Mac has, then kept in its Keychain. "
           "This app and the database never see it in plain text.")

if not public_key:
    st.warning("Your Mac isn't linked to the app yet. This is needed once: on your Mac, "
               "double-click Card Offers Helper in the project folder and click "
               "Turn on automatic sync. After that you can do everything here.")
elif mac_online:
    st.html(c.pill("Your Mac is online", "green"))
else:
    st.warning("Your Mac is offline" + (f" (last seen {refresh.local_time(seen_at)})"
               if seen_at else "") + ". Logins and syncs you start here will run when "
               "your Mac is on and awake.")

st.subheader("Banks")
for src in refresh.BANKS:
    name = refresh.SOURCES[src]
    label, tone = statuses[src]
    run = runs[src]
    with st.container(border=True, key=f"card-bank-{src}"):
        a, b = st.columns([3, 2], vertical_alignment="center")
        a.markdown(f"**{name}**")
        if src in pending:
            b.html(c.pill("Sending login to your Mac…", "blue"))
        elif src in saved:
            b.html(c.status_pill(label.split(": ", 1)[-1], tone) if run
                   else c.pill("Login saved", "green"))
        else:
            b.html(c.pill("Not connected", "gray"))
        if run:
            st.caption(c.md(f"Last run {refresh.local_time(run.started_at)}"
                            + (f" · {run.message[:200]}" if run.message else "")))
        if run and run.status == "needs_code":
            c.mfa_box(src, name)
        if src in saved:
            busy = bool(run and run.status in ("running", "needs_code"))
            if st.button("Syncing…" if busy else "Sync now", key=f"sync-{src}",
                         type="primary", disabled=busy):
                sync(src)
                st.toast(f"{name} sync requested. Your Mac starts it within a minute.")
        if public_key and src not in pending:
            with st.expander("Change login" if src in saved else f"Connect {name}",
                             expanded=src not in saved):
                with st.form(f"login-{src}", clear_on_submit=True):
                    user = st.text_input(f"{name} username", autocomplete="off")
                    pw = st.text_input(f"{name} password", type="password",
                                       autocomplete="off")
                    if st.form_submit_button("Connect", type="primary"):
                        if not user.strip() or not pw:
                            st.error("Enter both your username and password.")
                        else:
                            connect(src, user.strip(), pw)
                            st.toast(f"{name} login sent to your Mac. It logs in within "
                                     "a minute. Watch here for a security code request.")
                            st.rerun()

st.subheader("Gmail")
with st.container(border=True, key="card-gmail"):
    label, tone = statuses["gmail"]
    st.html(c.status_pill(label.split(": ", 1)[-1], tone))
    run = runs["gmail"]
    if run:
        st.caption(c.md(f"Last run {refresh.local_time(run.started_at)}"
                        + (f" · {run.message[:200]}" if run.message else "")))
    if hint := refresh.gmail_hint(run):
        st.warning(hint)
    st.caption("Checked every hour. If your banks email a different Gmail address, set "
               "that account to forward bank emails to this inbox.")

st.subheader("Cards")
st.html(c.bullet_list([
    f"{card['name']} ({card['issuer']})"
    + (f" ••{card['last_digits']}" if card.get("last_digits") else " · last digits not set")
    for card in cards_config()]))
st.page_link("views/my_cards.py", label="Edit cards")
