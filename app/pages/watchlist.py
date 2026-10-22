"""Watchlist: merchants I want offers for, with matching active offers."""

from html import escape

import streamlit as st
from sqlalchemy import func, select

from app import db, insights
from app.db import Watchlist
from app.ui import components as c


def remove(wid: int) -> None:
    with db.session() as s:
        if row := s.get(Watchlist, wid):
            s.delete(row)


st.title("Watchlist")
st.caption("You get an alert when any card gets an offer at one of these merchants.")

with st.form("add-watch", clear_on_submit=True):
    name = st.text_input("Merchant", placeholder="e.g. Costco", max_chars=120)
    if st.form_submit_button("Add", type="primary"):
        name = " ".join(name.split())
        if not name:
            st.error("Type a merchant name first.")
        else:
            with db.session() as s:
                exists = s.scalar(select(Watchlist.id).where(
                    func.lower(Watchlist.merchant_name) == name.lower()))
                if exists:
                    st.info(f"{name} is already on your watchlist.")
                else:
                    s.add(Watchlist(merchant_name=name))

today = insights.today()
with db.session() as s:
    items = s.scalars(select(Watchlist).order_by(Watchlist.merchant_name)).all()
    offers = insights.active_offers(s, today)

if not items:
    st.caption("Your watchlist is empty.")
for w in items:
    key = insights.norm(w.merchant_name)
    matches = [o for o in offers if key in insights.norm(o.merchant_name)]
    a, b = st.columns([5, 1], vertical_alignment="center")
    a.html(f'<div class="co-merchant">{escape(w.merchant_name)}</div>'
           + c.pill(f"{len(matches)} active offer{'s' if len(matches) != 1 else ''}",
                    "green" if matches else "gray"))
    b.button("Remove", key=f"rm-{w.id}", on_click=remove, args=(w.id,),
             width="stretch")
    if matches:
        st.html("".join(c.offer_row(o, c.card_info(o.card_id), today) for o in matches))
