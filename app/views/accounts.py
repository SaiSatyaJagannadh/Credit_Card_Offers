"""Accounts: per-source sync status, MFA code entry, Gmail connection, how to connect."""

import streamlit as st

from app import db, refresh
from app.config import cards_config
from app.ui import components as c

with db.session() as s:
    statuses = refresh.source_status(s)
    runs = {src: db.latest_sync(s, src) for src in refresh.SOURCES}

st.title("Accounts")
st.caption("Your banks are read by the Card Offers Helper on your Mac. Your bank "
           "passwords stay in your Mac's Keychain and never reach this app.")

st.subheader("Banks")
for src in refresh.BANKS:
    label, tone = statuses[src]
    run = runs[src]
    with st.container(border=True, key=f"card-bank-{src}"):
        a, b = st.columns([3, 2], vertical_alignment="center")
        a.markdown(f"**{refresh.SOURCES[src]}**")
        b.html(c.status_pill(label.split(": ", 1)[-1], tone))
        if run:
            st.caption(c.md(f"Last run {refresh.local_time(run.started_at)}"
                            + (f" · {run.message[:200]}" if run.message else "")))
        if run and run.status == "needs_code":
            c.mfa_box(src, refresh.SOURCES[src])
        elif not run:
            st.caption("Not connected yet. On your Mac, double-click Card Offers Helper in "
                       "the project folder and save your login there.")

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
