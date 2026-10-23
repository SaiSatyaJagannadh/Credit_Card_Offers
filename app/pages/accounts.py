"""Accounts: per-source sync status, MFA code entry, Gmail connection, how to connect."""

import streamlit as st

from app import db, refresh
from app.config import cards_config
from app.ui import components as c

ROBOT_BANK = {"amex": "amex", "bofa": "bofa", "wellsfargo": "wellsfargo"}

with db.session() as s:
    statuses = refresh.source_status(s)
    runs = {src: db.latest_sync(s, src) for src in refresh.SOURCES}

st.title("Accounts")
st.caption("Banks are read by the robot on your Mac; your bank passwords stay in your Mac's "
           "Keychain and never reach this app.")

st.subheader("Banks")
for src in refresh.BANKS:
    label, tone = statuses[src]
    run = runs[src]
    with st.container(border=True):
        a, b = st.columns([3, 2], vertical_alignment="center")
        a.markdown(f"**{refresh.SOURCES[src]}**")
        b.html(c.status_pill(label, tone))
        if run:
            st.caption(c.md(f"Last run {refresh.local_time(run.started_at)}"
                            + (f" · {run.message[:200]}" if run.message else "")))
        if run and run.status == "needs_code":
            c.mfa_box(src, refresh.SOURCES[src])
        elif not run:
            st.caption("Not connected yet. On your Mac, in the project folder, run:")
            st.code(f".venv/bin/python -m robot.setup {ROBOT_BANK[src]}\n"
                    f".venv/bin/python -m robot.runner --once --bank {ROBOT_BANK[src]} --headed",
                    language="bash")

st.subheader("Gmail")
with st.container(border=True):
    st.html(c.status_pill(*statuses["gmail"]))
    run = runs["gmail"]
    if run:
        st.caption(c.md(f"Last run {refresh.local_time(run.started_at)}"
                        + (f" · {run.message[:200]}" if run.message else "")))
    if hint := refresh.gmail_hint(run):
        st.warning(hint)
    st.caption("Checked every hour. Forward bank emails from your other Gmail accounts to "
               "this inbox (README: Forward bank emails).")

st.subheader("Cards")
st.html(c.bullet_list([
    f"{card['name']} ({card['issuer']})"
    + (f" ••{card['last_digits']}" if card.get("last_digits") else " · last digits not set")
    for card in cards_config()]))
st.page_link("pages/my_cards.py", label="Edit cards")
