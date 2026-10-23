"""Search / Ask: "merchant + amount" -> best card; free text -> LLM over my own rows."""

import re
from datetime import timedelta

import streamlit as st
from sqlalchemy import select

from app import db, insights, ranking
from app.config import cards_config
from app.db import Transaction
from app.ui import components as c

AMOUNT = r"\$?(\d{1,6}(?:\.\d{1,2})?)"
PATTERNS = [  # "best card for $40 at Uber?", "$40 at uber", "uber 40", "40 uber"
    re.compile(rf"^(?:what(?:'s| is) the )?(?:best card for )?{AMOUNT} (?:at|on|for) (.+)$"),
    re.compile(rf"^(?:best card (?:at|for) )?(.+?) {AMOUNT}$"),
    re.compile(rf"^{AMOUNT} (.+)$"),
]
QUESTION_WORDS = ("what", "how", "which", "when", "where", "why", "who", "do", "did", "does",
                  "is", "are", "can", "should", "show", "list")


def parse_purchase(q: str) -> tuple[str, float] | None:
    q = " ".join(q.lower().strip(" ?.!").split())
    for i, p in enumerate(PATTERNS):
        if m := p.match(q):
            amount, merchant = (m[2], m[1]) if i == 1 else (m[1], m[2])
            if merchant.split()[0] in QUESTION_WORDS or len(merchant.split()) > 4:
                return None  # a question that happens to end in a number
            return merchant.strip(), float(amount)
    return None


def show_options(merchant: str, amount: float) -> None:
    today = insights.today()
    with db.session() as s:
        opts = insights.best_for_purchase(s, merchant, amount, today)
        found = insights.offers_for_merchant(s, merchant, today)
    st.subheader(c.md(f"Best card for {c.money(amount)} at {merchant.title()}"))
    if not found:
        st.caption(f"No active offers at {merchant.title()}; ranking by base rewards only.")
    st.html(c.option_card(opts[0], c.card_info(opts[0].card_id), today, best=True))
    with st.expander("Your other cards, ranked", expanded=True):
        st.html("".join(c.option_card(o, c.card_info(o.card_id), today) for o in opts[1:]))


def ask_llm(question: str) -> None:
    since = insights.today() - timedelta(days=90)
    with db.session() as s:
        offers = [{"merchant": o.merchant_name, "card": c.card_info(o.card_id)["name"],
                   "text": o.offer_text, "value": ranking.offer_max_value(o),
                   "expires": o.expires_on.isoformat() if o.expires_on else None,
                   "enrolled": o.enrolled, "exclusions": o.exclusions}
                  for o in insights.active_offers(s)]
        txns = [{"merchant": t.merchant_raw, "card": c.card_info(t.card_id)["name"],
                 "amount": t.amount, "date": t.date.isoformat()}
                for t in s.scalars(select(Transaction).where(Transaction.date >= since))]
    context = {"offers": offers, "cards": cards_config(), "transactions": txns}
    try:
        from app.llm import answer_question

        with st.spinner("Thinking…"):
            answer = answer_question(question, context)
    except ImportError:
        st.error("The AI assistant isn't set up yet (app/llm.py is missing). Try a purchase "
                 "instead, like \"$40 at Uber\".")
        return
    except Exception as e:
        detail = str(e).rstrip(".")
        st.error(f"Couldn't get an answer from the AI provider: {type(e).__name__}: {detail}. "
                 "Check LLM_PROVIDER, LLM_MODEL and the API key in secrets.")
        return
    st.markdown(c.md(answer))  # markdown escapes HTML; md() keeps "$" literal


st.title("Search")
q = st.text_input("Search or ask", key="search_q",  # Dashboard pre-fills this key
                  placeholder="Search or ask: best card for $40 at Uber?")
if q.strip():
    if parsed := parse_purchase(q):
        show_options(*parsed)
    else:
        ask_llm(q.strip())

st.divider()
st.subheader("I'm at…")
a, b = st.columns([3, 1])
store = a.text_input("Store name", placeholder="e.g. Lyft")
amount = b.number_input("Amount ($)", min_value=1.0, max_value=100000.0, value=50.0, step=5.0)
if store.strip():
    today = insights.today()
    with db.session() as s:
        here = insights.offers_for_merchant(s, store.strip(), today)
    if here:
        st.html("".join(c.offer_row(o, c.card_info(o.card_id), today) for o in here))
    show_options(store.strip(), amount)
