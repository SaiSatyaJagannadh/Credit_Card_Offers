"""Get started: how the app works, and a live setup checklist."""

from html import escape

import streamlit as st

from app import db, setup_status
from app.ui import components as c

logged_in = bool(getattr(st.user, "is_logged_in", False))
with db.session() as s:
    steps = setup_status.steps(s, logged_in)
done = sum(x.done for x in steps)

st.title("Get started")
st.write("Card Offers puts every card-linked offer from your cards in one place, tells you "
         "which card to pay with, and emails you before offers run out.")

st.subheader("How it works")
FLOW = [
    ("Bank robot", "On your Mac, every day at 7 AM",
     "Logs in to Amex, Bank of America and Wells Fargo as you and reads the offers on your "
     "account."),
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
    '<div class="co-card co-flow-out"><div class="co-title">Your offers database</div>'
    '<div class="co-muted">Feeds the dashboard, best-card answers, missed savings, the credit '
    "watchdog and your email alerts.</div></div>")

st.subheader("Setup")
st.progress(done / len(steps), text=f"{done} of {len(steps)} done")

for i, x in enumerate(steps, 1):
    with st.container(border=True, key=f"card-step-{x.key}"):
        a, b = st.columns([4, 1], vertical_alignment="center")
        a.markdown(f"**{i}. {x.title}**")
        b.html(c.pill("Done", "green") if x.done else c.pill("To do", "amber"))
        st.caption(c.md(x.status))
        if not x.done:
            st.write(c.md(x.how))
            if x.command:
                st.code(x.command, language="bash")
            if x.page:
                st.page_link(x.page, label="Open " + {
                    "views/my_cards.py": "My cards", "views/accounts.py": "Accounts",
                    "views/add.py": "Add & edit"}[x.page])

st.caption("Cloud keys (database, login, AI, Gmail, GitHub) are set once in Streamlit and "
           "GitHub secrets. Step-by-step instructions are in the README.")
