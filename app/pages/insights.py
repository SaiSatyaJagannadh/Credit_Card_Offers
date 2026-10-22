"""Insights: missed savings, credit watchdog, spend progress."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import select

from app import db, insights
from app.db import ExpectedCredit, Offer, Transaction
from app.ui import components as c

today = insights.today()
with db.session() as s:
    misses = insights.missed_savings(s, date(today.year, 1, 1))
    watch = s.execute(
        select(ExpectedCredit, Offer, Transaction)
        .join(Offer, Offer.id == ExpectedCredit.offer_id)
        .join(Transaction, Transaction.id == ExpectedCredit.transaction_id)
        .order_by(ExpectedCredit.due_on)).all()
    progress = insights.spend_progress(s, today)


def had(opt) -> str:
    if opt.offer is not None:
        o = opt.offer
        return f"{o.pct:g}% back" if o.type == "pct" else f"{c.money(opt.offer_value)} back"
    return f"{opt.base_rate * 100:g}% back"


st.title("Insights")

st.subheader(f"Missed savings in {today.year}")
by_month = insights.missed_by_month(misses)
if misses:
    st.metric("Total missed", c.money(sum(by_month.values())))
    df = pd.DataFrame({"Month": list(by_month), "Missed": list(by_month.values())})
    st.altair_chart(alt.Chart(df).mark_bar(color="#8A4B00", cornerRadiusEnd=4).encode(
        x=alt.X("Month:N", title=None, sort=None), y=alt.Y("Missed:Q", title="Missed ($)"),
        tooltip=["Month", alt.Tooltip("Missed:Q", format="$,.2f")]), width="stretch")
    top5 = sorted(misses, key=lambda m: -m.missed)[:5]
    st.markdown("**Top misses**")
    st.html(c.bullet_list([
        f"{m.merchant} on {c.card_info(m.txn.card_id)['name']}: missed {c.money(m.missed)}, "
        f"{m.best.card_name} had {had(m.best)}" for m in top5]))
else:
    st.caption("No missed savings this year. Nice.")

st.subheader("Credit watchdog")
if watch:
    rows = []
    for ec, offer, txn in watch:
        status = "overdue" if ec.status == "waiting" and ec.due_on < today else ec.status
        rows.append({"Merchant": offer.merchant_name, "Card": c.card_info(txn.card_id)["name"],
                     "Purchase": txn.date, "Amount": txn.amount, "Expected credit": ec.amount,
                     "Due": ec.due_on, "Status": status})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Amount": st.column_config.NumberColumn(format="$%.2f"),
        "Expected credit": st.column_config.NumberColumn(format="$%.2f")})
    for (ec, offer, txn), row in zip(watch, rows, strict=True):
        if row["Status"] != "overdue":
            continue
        card = c.card_info(txn.card_id)
        digits = f" ending {card['last_digits']}" if card.get("last_digits") else ""
        st.markdown("**Overdue credit** (copy and send to the bank):")
        st.code(
            f"Purchase date: {txn.date:%B %d, %Y}\n"
            f"Merchant: {offer.merchant_name}\n"
            f"Amount: ${txn.amount:,.2f} on {card['name']}{digits}\n"
            f"Offer: {offer.offer_text}\n"
            f"Expected credit: ${ec.amount:,.2f}, due by {ec.due_on:%B %d, %Y}, not received.",
            language=None)
else:
    st.caption("No purchases waiting on an offer credit.")

st.subheader("Spend progress")
if progress:
    for p in progress:
        st.progress(min(p.spent / p.target, 1.0), text=c.md(
            f"{p.offer.merchant_name}: {c.money(p.spent, False)} of {c.money(p.target, False)}"))
else:
    st.caption("No min-spend offers right now.")
