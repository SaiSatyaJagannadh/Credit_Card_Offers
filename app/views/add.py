"""Add & edit: enter offers, purchases and credits by hand; mark offers added; fix mistakes."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select

from app import db, insights, ranking
from app.config import cards_config
from app.db import Credit, ExpectedCredit, Offer, Transaction
from workers.match import CATEGORIES, merchant_for, upsert_offer

cards = {c["id"]: c for c in cards_config()}
offer_cards = [cid for cid, c in cards.items() if c.get("offers_program")]
today = insights.today()


def card_label(cid: str) -> str:
    c = cards[cid]
    return c["name"] + (f" (ending {c['last_digits']})" if c.get("last_digits") else "")


def done(msg: str) -> None:
    st.toast(msg)
    st.rerun()


st.title("Add & edit")
st.caption("Offers, purchases and credits you enter here are used everywhere: best-card "
           "ranking, expiry emails, missed savings and the credit watchdog.")

t_offer, t_buy, t_credit, t_manage = st.tabs(["Add offer", "Add purchase", "Add credit",
                                               "Manage offers"])

with t_offer, st.form("offer", clear_on_submit=True):
    a, b = st.columns(2)
    card_id = a.selectbox("Card", offer_cards, format_func=card_label)
    merchant = b.text_input("Merchant", placeholder="e.g. Dell")
    a, b, c = st.columns(3)
    kind = a.radio("Offer type", ["% back", "$ back"], horizontal=True)
    value = b.number_input("Value (% or $)", min_value=0.0, step=1.0)
    max_credit = c.number_input("Max credit $ (for % offers)", min_value=0.0, step=1.0)
    a, b, c = st.columns(3)
    min_spend = a.number_input("Minimum spend $", min_value=0.0, step=5.0)
    expires = b.date_input("Expires", value=today + timedelta(days=30), min_value=today)
    category = c.selectbox("Merchant category", CATEGORIES, index=CATEGORIES.index("other"),
                           format_func=lambda x: x.replace("_", " ").title())
    a, b = st.columns([2, 1])
    exclusions = a.text_input("Exclusions (optional)", placeholder="e.g. not via PayPal")
    enrolled = b.checkbox("Already added to card")
    if st.form_submit_button("Save offer", type="primary"):
        if not merchant.strip() or value <= 0:
            st.error("Enter a merchant and a value above 0.")
        elif kind == "% back" and value > 100:
            st.error("A percent offer can't be more than 100%.")
        else:
            pct = kind == "% back"
            text = (f"{value:g}% back" + (f", up to ${max_credit:g}" if max_credit else "")
                    if pct else f"${value:g} back") + (
                f" on ${min_spend:g}+" if min_spend else "")
            o = SimpleNamespace(
                merchant=merchant.strip(), offer_text=text, type="pct" if pct else "fixed",
                pct=value if pct else None, fixed_amount=None if pct else value,
                min_spend=min_spend or None, max_credit=(max_credit or None) if pct else None,
                expires_on=expires, channel="both", exclusions=exclusions.strip(),
                enrolled=enrolled)
            with db.session() as s:
                merchant_for(s, o.merchant, category)
                upsert_offer(s, cards[card_id]["issuer"], card_id, o, "manual", None)
            done(f"Saved {o.merchant} offer.")

with t_buy, st.form("purchase", clear_on_submit=True):
    a, b = st.columns(2)
    card_id = a.selectbox("Card used", list(cards), format_func=card_label)
    merchant = b.text_input("Merchant", placeholder="e.g. Costco")
    a, b, c = st.columns(3)
    amount = a.number_input("Amount $", min_value=0.0, step=1.0)
    when = b.date_input("Date", value=today, max_value=today)
    category = c.selectbox("Category", CATEGORIES, index=CATEGORIES.index("other"),
                           format_func=lambda x: x.replace("_", " ").title(), key="buy-cat")
    if st.form_submit_button("Save purchase", type="primary"):
        if not merchant.strip() or amount <= 0:
            st.error("Enter a merchant and an amount above 0.")
        else:
            with db.session() as s:
                m = merchant_for(s, merchant, category)
                s.add(Transaction(card_id=card_id, merchant_raw=merchant.strip(),
                                  merchant_id=m.id, amount=round(amount, 2), date=when,
                                  source_message_id=f"manual:{uuid.uuid4()}"))
                s.flush()
                insights.create_expected_credits(s)
            done("Purchase saved.")

with t_credit, st.form("credit", clear_on_submit=True):
    a, b = st.columns(2)
    card_id = a.selectbox("Card", list(cards), format_func=card_label, key="credit-card")
    merchant = b.text_input("Merchant on the credit", placeholder="e.g. Dell")
    a, b = st.columns(2)
    amount = a.number_input("Credit amount $", min_value=0.0, step=1.0)
    when = b.date_input("Date posted", value=today, max_value=today)
    if st.form_submit_button("Save credit", type="primary"):
        if not merchant.strip() or amount <= 0:
            st.error("Enter a merchant and an amount above 0.")
        else:
            with db.session() as s:
                m = merchant_for(s, merchant, "other")
                s.add(Credit(card_id=card_id, merchant_raw=merchant.strip(), merchant_id=m.id,
                             amount=round(amount, 2), date=when,
                             source_message_id=f"manual:{uuid.uuid4()}"))
                s.flush()
                insights.update_expected_credits(s)
            done("Credit saved.")

with t_manage:
    with db.session() as s:
        offers = insights.active_offers(s, today)
    if not offers:
        st.caption("No active offers yet. Add one above, or let the bank robot and Gmail "
                   "reader find them.")
    else:
        st.caption("Tick Added once you've added an offer on the bank's site. Tick Delete to "
                   "remove an offer you entered by mistake.")
        df = pd.DataFrame([{
            "id": o.id, "Added": o.enrolled, "Delete": False, "Merchant": o.merchant_name,
            "Up to $": ranking.offer_max_value(o), "Expires": o.expires_on,
            "Card": cards[o.card_id]["name"], "Offer": o.offer_text,
        } for o in sorted(offers, key=lambda o: (o.expires_on is None, o.expires_on))])
        edited = st.data_editor(
            df, hide_index=True, width="stretch", key="manage",
            disabled=[col for col in df.columns if col not in ("Added", "Delete")],
            column_config={"id": None, "Up to $": st.column_config.NumberColumn(format="$%.0f")})
        if st.button("Save changes", type="primary"):
            with db.session() as s:
                for r in edited.to_dict("records"):
                    o = s.get(Offer, r["id"])
                    if r["Delete"]:
                        s.execute(delete(ExpectedCredit).where(ExpectedCredit.offer_id == o.id))
                        s.execute(Credit.__table__.update().where(Credit.offer_id == o.id)
                                  .values(offer_id=None))
                        s.delete(o)
                    else:
                        o.enrolled = bool(r["Added"])
                s.flush()
                insights.create_expected_credits(s)
            done("Changes saved.")

    with db.session() as s:
        recent = s.scalars(select(Transaction).where(Transaction.source_message_id
                                                     .like("manual:%"))
                           .order_by(Transaction.id.desc()).limit(10)).all()
    if recent:
        st.subheader("Purchases you entered")
        for t in recent:
            a, b = st.columns([5, 1], vertical_alignment="center")
            a.text(f"{t.date:%b %d}  {t.merchant_raw}  ${t.amount:,.2f}  "
                   f"{card_label(t.card_id)}")
            if b.button("Delete", key=f"del-t-{t.id}"):
                with db.session() as s:
                    s.execute(delete(ExpectedCredit).where(ExpectedCredit.transaction_id == t.id))
                    s.execute(delete(Transaction).where(Transaction.id == t.id))
                done("Purchase deleted.")
