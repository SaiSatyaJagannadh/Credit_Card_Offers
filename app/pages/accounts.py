"""Accounts: per-source sync status, MFA code entry, Gmail connection, cards."""

import pandas as pd
import streamlit as st

from app import db, refresh
from app.config import cards_config
from app.ui import components as c

with db.session() as s:
    statuses = refresh.source_status(s)
    runs = {src: db.latest_sync(s, src) for src in refresh.SOURCES}

st.title("Accounts")

st.subheader("Banks")
for src in refresh.BANKS:
    label, tone = statuses[src]
    run = runs[src]
    with st.container(border=True):
        st.html(c.status_pill(label, tone))
        if run:
            st.caption(c.md(f"Last run started {refresh.local_time(run.started_at)}"
                            + (f": {run.message[:200]}" if run.message else "")))
        c.mfa_box(src, refresh.SOURCES[src])

st.subheader("Gmail")
with st.container(border=True):
    st.html(c.status_pill(*statuses["gmail"]))
    run = runs["gmail"]
    if run:
        st.caption(c.md(f"Last run started {refresh.local_time(run.started_at)}"
                        + (f": {run.message[:200]}" if run.message else "")))
    if hint := refresh.gmail_hint(run):
        st.warning(hint)
    st.caption("The Gmail reader runs hourly on GitHub Actions. Tokens live in secrets, "
               "never in the database. Setup and reconnect steps are in the README.")

st.subheader("Cards")
st.dataframe(pd.DataFrame([{
    "Card": card["name"], "Issuer": card["issuer"],
    "Last digits": f"••{card['last_digits']}" if card.get("last_digits") else "not set",
    "Offers program": card.get("offers_program") or "None",
} for card in cards_config()]), hide_index=True, width="stretch")
