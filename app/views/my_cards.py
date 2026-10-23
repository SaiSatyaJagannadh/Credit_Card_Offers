"""My cards: last digits, BofA 3% choice, Discover 5% quarter, bonus categories.
Saved as DB setting "card_overrides", layered over config/cards.yaml."""

import re

import pandas as pd
import streamlit as st

from app import db, ranking
from app.config import _yaml_cards, cards_config
from app.insights import today
from workers.match import CATEGORIES

CHOICES = ["gas", "online", "dining", "travel", "drugstores", "home_improvement"]
LABEL = {c: c.replace("_", " ").title() for c in CATEGORIES}
q = ranking.quarter_key(today())
yaml_by_id = {c["id"]: c for c in _yaml_cards()}


def save(card_id: str, patch: dict) -> None:
    with db.session() as s:
        overrides = db.get_setting(s, "card_overrides", {})
        overrides[card_id] = {**overrides.get(card_id, {}), **patch}
        db.set_setting(s, "card_overrides", overrides)
        db.sync_cards(s)  # reloads overrides + updates the cards table


st.title("My cards")
st.caption("Card names and last digits only. Never enter a full card number here.")

for card in cards_config():
    base = yaml_by_id[card["id"]]
    with st.container(border=True, key=f"card-{card['id']}"):
        st.subheader(card["name"])
        st.caption(f"{card['issuer']} · {card.get('offers_program') or 'No offers program'}")
        with st.form(f"card-{card['id']}", border=False):
            digits = st.text_input("Last digits (4 or 5)", value=card.get("last_digits") or "",
                                   max_chars=5, placeholder="e.g. 1234")
            patch: dict = {}
            if "choice" in base.get("categories", {}):
                cur = card.get("choice_category") or "online"
                patch["choice_category"] = st.selectbox(
                    "3% choice category", CHOICES, index=CHOICES.index(cur)
                    if cur in CHOICES else 1, format_func=LABEL.get)
            if base.get("rotating") is not None:
                rot = card.get("rotating", {}).get(q, {"categories": [], "activated": False})
                cats = st.multiselect(f"5% categories for {q}", CATEGORIES,
                                      default=[c for c in rot["categories"] if c in CATEGORIES],
                                      format_func=LABEL.get)
                act = st.checkbox("I activated this quarter's 5%", value=rot.get("activated"))
                patch["rotating"] = {q: {"categories": cats, "activated": act}}
            if not base.get("categories"):
                st.caption(f"Everything else earns {card['base_rate'] * 100:g}%. "
                           "Add bonus categories if this card has any.")
                rows = pd.DataFrame(
                    [{"Category": k, "Rate %": v["rate"] * 100}
                     for k, v in card.get("categories", {}).items()],
                    columns=["Category", "Rate %"])
                edited = st.data_editor(
                    rows, num_rows="dynamic", hide_index=True, width="stretch",
                    key=f"bonus-{card['id']}", column_config={
                        "Category": st.column_config.SelectboxColumn(options=CATEGORIES,
                                                                     required=True),
                        "Rate %": st.column_config.NumberColumn(min_value=0.0, max_value=10.0,
                                                                step=0.5, required=True)})
            if st.form_submit_button("Save", type="primary"):
                digits = digits.strip()
                if digits and not re.fullmatch(r"\d{4,5}", digits):
                    st.error("Last digits must be 4 or 5 numbers.")
                    st.stop()
                patch["last_digits"] = digits
                if not base.get("categories"):
                    patch["categories"] = {
                        r["Category"]: {"rate": float(r["Rate %"]) / 100}
                        for r in edited.dropna().to_dict("records")}
                save(card["id"], patch)
                st.success("Saved.")
                st.rerun()
