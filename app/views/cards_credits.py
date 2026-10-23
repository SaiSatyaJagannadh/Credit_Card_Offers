"""Cards & credits: best card per category, cap trackers, saved-from-offers chart, cards."""

import pandas as pd
import streamlit as st

from app import db, insights, ranking
from app.config import cards_config
from app.ui import components as c

today = insights.today()
with db.session() as s:
    cap_used = insights.cap_used_now(s, today)
    saved = insights.credits_by_month(s, today.year)
cards = cards_config()


def pct(rate: float) -> str:
    return f"{rate * 100:g}%"


st.title("Cards & credits")

st.subheader("Best card per category")
st.dataframe(pd.DataFrame([
    {"Category": cat.replace("_", " ").title(), "Card": card["name"], "Rate": pct(r.rate),
     "Note": r.note} for cat, card, r in ranking.best_card_per_category(today)
]), hide_index=True, width="stretch")
notes = []
for card in cards:
    if card.get("choice_category"):
        notes.append(f"{card['name']} 3% choice category: "
                     f"{card['choice_category'].replace('_', ' ')} (review monthly).")
    if rot := card.get("rotating", {}).get(ranking.quarter_key(today)):
        state = "activated" if rot.get("activated") else "NOT activated yet"
        notes.append(f"{card['name']} {pct(card['rotating_rate'])} this quarter: "
                     f"{', '.join(rot['categories'])} ({state}).")
if notes:
    st.html(c.bullet_list(notes))

st.subheader("Caps and credits")
any_cap = False
for card in cards:
    for key, cap in (card.get("caps") or {}).items():
        any_cap = True
        used = cap_used.get(f"{card['id']}:{key}", 0.0)
        st.progress(min(used / cap["limit"], 1.0), text=c.md(
            f"{card['name']} — {cap['label']}: {c.money(used, False)} of "
            f"{c.money(cap['limit'], False)} this {cap['period']}"))
    for credit in card.get("monthly_credits") or []:
        any_cap = True
        st.caption(c.md(f"{card['name']}: {credit['name']} {c.money(credit['amount'])}/month"))
if not any_cap:
    st.caption("No caps or monthly credits in cards.yaml.")

st.subheader("Saved from offers")
if saved:
    c.month_bars(saved, "#0B6E4F", "Saved")
else:
    st.caption(f"No credits posted in {today.year} yet.")

st.subheader("Your cards")
st.dataframe(pd.DataFrame([{
    "Card": card["name"] + (f" ••{card['last_digits']}" if card.get("last_digits") else ""),
    "Issuer": card["issuer"],
    "Bonus categories": (", ".join(
        f"{(card.get('choice_category') if k == 'choice' else k).replace('_', ' ')} "
        f"{pct(v['rate'])}" for k, v in (card.get("categories") or {}).items())
        + (f"; rotating {pct(card['rotating_rate'])}" if card.get("rotating") else "")
        ).strip("; ") or "None",
    "Everything else": pct(card["base_rate"]),
    "Offers program": card.get("offers_program") or "None",
} for card in cards]), hide_index=True, width="stretch")
