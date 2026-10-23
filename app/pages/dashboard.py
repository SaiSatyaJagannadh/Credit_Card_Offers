"""Dashboard: KPIs, to-dos, top offers, expiring soon, accounts, credits, Gmail status."""

from datetime import date, datetime

import streamlit as st
from sqlalchemy import func, select

from app import db, insights, ranking, refresh
from app.db import Credit, SyncRun, TodoDone, Watchlist
from app.ui import components as c

today = insights.today()
with db.session() as s:
    k = insights.kpis(s, today)
    todos = insights.todos(s, today)
    offers = insights.active_offers(s, today)
    shop = insights.shopped_merchants(s, today)
    watch = {insights.norm(w) for w in s.scalars(select(Watchlist.merchant_name))}
    prev = insights.previous_sync_start(s)
    statuses = refresh.source_status(s)
    gmail_run = db.latest_sync(s, "gmail")
    credits = s.scalars(select(Credit).order_by(Credit.date.desc()).limit(5)).all()
    last = s.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.status == "ok"))


def mark_done(key: str) -> None:
    with db.session() as s:
        s.merge(TodoDone(key=key))


st.title("Card Offers")
st.caption(f"Last synced {refresh.local_time(last)}" if last else "Not synced yet")

if not offers:
    with st.container(border=True):
        st.subheader("Welcome — let's load your offers")
        st.write("No offers yet. Three ways to fill this page:")
        a, b, cc = st.columns(3)
        a.markdown("**1. Set up your cards**  \nLast digits, BofA 3% choice, Discover 5%.")
        a.page_link("pages/my_cards.py", label="Open My cards")
        b.markdown("**2. Add an offer you see**  \nIn your bank app? Enter it in a minute.")
        b.page_link("pages/add.py", label="Open Add & edit")
        cc.markdown("**3. Connect your banks**  \nThe robot on your Mac reads every offer.")
        cc.page_link("pages/accounts.py", label="Open Accounts")

top = st.columns([4, 1], vertical_alignment="bottom")
with top[0].form("ask", clear_on_submit=True, border=False):
    q = st.text_input("Search or ask", placeholder="Search or ask: best card for $40 at Uber?",
                      label_visibility="collapsed")
    if st.form_submit_button("Search") and q.strip():
        st.session_state["search_q"] = q.strip()
        st.switch_page("pages/search.py")
if top[1].button("Refresh now", type="primary", width="stretch"):
    st.session_state["refresh_msgs"] = refresh.request_refresh()
for m in st.session_state.get("refresh_msgs", []):
    st.info(c.md(m))

tiles = st.columns(4)
names = ", ".join(o.merchant_name for o in k.expiring_7[:3]) or "None"
for col, html in zip(tiles, [
    c.kpi_tile("Value on your cards", c.money(k.value_total, False), f"{len(offers)} offers"),
    c.kpi_tile("Not added yet", c.money(k.not_added_value, False), f"{k.not_added_count} offers"),
    c.kpi_tile("Expiring in 7 days", str(len(k.expiring_7)), names),
    c.kpi_tile("Saved this year", c.money(k.saved_this_year), "Credits posted"),
], strict=True):
    col.html(html)

main, side = st.columns([2, 1], gap="large")

with main:
    st.subheader("To-do")
    if not todos:
        st.caption("Nothing to do right now.")
    LINK_LABEL = {"add_offer": "Add to card", "activate": "Activate", "review": "Review"}
    for t in todos:
        a, b = st.columns([5, 1], vertical_alignment="center")
        a.html(c.todo_card(t.title, t.detail, t.action, LINK_LABEL.get(t.kind, "Open")))
        if t.kind == "mfa":
            a.page_link("pages/accounts.py", label="Enter code on Accounts")
        b.button("Done", key=f"done-{t.key}", on_click=mark_done, args=(t.key,),
                 width="stretch")

    st.subheader("Top offers")
    f1, f2 = st.columns(2)
    view = f1.radio("Show", ["All", "For you", "Not added", "Added"], horizontal=True,
                    label_visibility="collapsed")
    sort = f2.selectbox("Sort", ["Highest value", "Expiring first", "Newest"],
                        label_visibility="collapsed")

    def for_you(o) -> bool:
        return insights.norm(o.merchant_name) in shop | watch

    rows = [o for o in offers if view == "All" or (view == "For you" and for_you(o))
            or (view == "Not added" and not o.enrolled) or (view == "Added" and o.enrolled)]
    if sort == "Highest value":
        rows.sort(key=lambda o: -ranking.offer_max_value(o))
    elif sort == "Expiring first":
        rows.sort(key=lambda o: o.expires_on or date.max)
    else:
        rows.sort(key=lambda o: o.first_seen_at or datetime.min, reverse=True)
    if rows:
        st.html("".join(c.offer_row(o, c.card_info(o.card_id), today, insights.is_new(o, prev),
                                    insights.norm(o.merchant_name) in shop) for o in rows))
    else:
        st.caption("No offers match this filter.")

    st.subheader("Use these before they expire")
    if k.expiring_7:
        st.html("".join(c.offer_row(o, c.card_info(o.card_id), today) for o in k.expiring_7))
    else:
        st.caption("Nothing expires in the next 7 days.")

with side:
    st.subheader("Connected accounts")
    for src, (label, tone) in statuses.items():
        st.html(c.status_pill(label, tone))
        if label.endswith("needs security code"):
            c.mfa_box(src, refresh.SOURCES[src])

    st.subheader("Credits posted")
    if credits:
        st.html(c.bullet_list([
            f"{cr.merchant_raw}: {c.money(cr.amount)} on {c.card_info(cr.card_id)['name']}, "
            f"{cr.date:%b} {cr.date.day}" for cr in credits]))
    else:
        st.caption("No credits yet.")

    st.subheader("Gmail reader")
    st.html(c.status_pill(*statuses["gmail"]))
    if gmail_run and gmail_run.message:
        st.caption(c.md(gmail_run.message[:200]))
    if hint := refresh.gmail_hint(gmail_run):
        st.warning(hint)
