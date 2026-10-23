"""Get started: the next setup step up front, what's left, what's done, how it works."""

from html import escape

import streamlit as st

from app import db, setup_status
from app.ui import components as c

PAGE_LABEL = {"views/my_cards.py": "Set up my cards", "views/accounts.py": "Open Accounts",
              "views/add.py": "Add an offer"}

logged_in = bool(getattr(st.user, "is_logged_in", False))
with db.session() as s:
    steps = setup_status.steps(s, logged_in)
todo = [x for x in steps if not x.done]
done = [x for x in steps if x.done]

st.title("Get started")
st.write("Card Offers collects the offers on your cards, tells you which card to pay with, "
         "and emails you before offers run out.")
st.progress(len(done) / len(steps), text=f"Setup: {len(done)} of {len(steps)} done")

if todo:
    nxt = todo[0]
    with st.container(border=True, key="card-next"):
        st.caption("Your next step")
        st.subheader(nxt.title)
        st.write(c.md(nxt.how))
        st.caption(c.md(f"Right now: {nxt.status}"))
        if nxt.page and st.button(PAGE_LABEL[nxt.page], type="primary"):
            st.switch_page(nxt.page)
else:
    with st.container(border=True, key="card-next"):
        st.subheader("You're all set")
        st.write("Offers now arrive by themselves. Check the dashboard any time.")
        if st.button("Open dashboard", type="primary"):
            st.switch_page("views/dashboard.py")

if len(todo) > 1:
    st.subheader("Still to do")
    for x in todo[1:]:
        with st.container(border=True, key=f"card-step-{x.key}"):
            a, b = st.columns([4, 1], vertical_alignment="center")
            a.markdown(f"**{x.title}**")
            b.html(c.pill("To do", "amber"))
            st.write(c.md(x.how))
            st.caption(c.md(f"Right now: {x.status}"))
            if x.page:
                st.page_link(x.page, label=PAGE_LABEL[x.page])

if done:
    with st.expander(f"Done ({len(done)})"):
        st.html(c.bullet_list([f"{x.title}: {x.status}" for x in done]))

st.subheader("How it works")
FLOW = [
    ("Bank robot", "On your Mac, every day at 7 AM",
     "Signs in to Amex, Bank of America and Wells Fargo as you and reads the offers on your "
     "accounts. You connect each bank on Accounts."),
    ("Gmail reader", "In the cloud, every hour",
     "Reads only bank emails: new offers, purchases and credits posted."),
    ("You", "Any time, on Add & edit",
     "Type in an offer you saw, a purchase, or a credit."),
]
st.html(
    '<div class="co-flow">'
    + "".join(f'<div class="co-card co-flow-src"><div class="co-title">{escape(t)}</div>'
              f'<div class="co-when">{escape(w)}</div><div class="co-muted">{escape(d)}</div>'
              "</div>" for t, w, d in FLOW)
    + '</div><div class="co-flow-into" aria-hidden="true"></div>'
    '<div class="co-card co-flow-out"><div class="co-title">Your offers</div>'
    '<div class="co-muted">Feed the dashboard, best-card answers, missed savings, the credit '
    "watchdog and your email alerts.</div></div>")
