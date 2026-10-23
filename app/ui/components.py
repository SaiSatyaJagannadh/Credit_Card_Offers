"""Reusable HTML pieces. Every data value goes through html.escape (merchant names come
from emails). Render with st.html (not st.markdown, which would read "$" as LaTeX)."""

import re
from datetime import date
from html import escape
from typing import Any

import streamlit as st

from app import ranking
from app.config import cards_config
from app.db import MfaCode, session

TONES = {"green", "amber", "blue", "purple", "gray"}
GRADE_TONE = {"A": "green", "B": "blue", "C": "gray"}


def md(text: str) -> str:
    """Make text safe for markdown widgets (captions, progress text): "$" is not LaTeX."""
    return text.replace("$", "\\$")


def money(x: float, cents: bool = True) -> str:
    return f"${x:,.2f}" if cents else f"${x:,.0f}"


def pill(text: str, tone: str = "gray") -> str:
    tone = tone if tone in TONES else "gray"
    return f'<span class="co-pill co-{tone}">{escape(text)}</span>'


def status_pill(label: str, tone: str) -> str:
    return pill(label, tone)


def link(url: str | None, label: str) -> str:
    if not url or not url.startswith(("https://", "http://")):
        return ""
    return (f'<a class="co-btn" href="{escape(url)}" target="_blank" rel="noopener">'
            f"{escape(label)}</a>")


def kpi_tile(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="co-sub">{escape(sub)}</div>' if sub else ""
    return (f'<div class="co-card co-kpi"><div class="co-label">{escape(label)}</div>'
            f'<div class="co-value">{escape(value)}</div>{sub_html}</div>')


def card_info(card_id: str) -> dict:
    """cards.yaml entry, or a bare stand-in if the DB has a card id the config lacks."""
    return next((c for c in cards_config() if c["id"] == card_id), {"id": card_id, "name": card_id})


def card_chip(card: dict) -> str:
    digits = f" ending {card['last_digits']}" if card.get("last_digits") else ""
    return pill(f"{card['name']}{digits}", "gray")


def expiry_chip(expires_on: date | None, today: date) -> str:
    if not expires_on:
        return ""
    days = (expires_on - today).days
    when = {0: "today", 1: "tomorrow"}.get(days, f"{expires_on:%b} {expires_on.day}")
    return pill(f"Expires {when}", "amber" if days <= 7 else "gray")


def offer_row(offer: Any, card: dict, today: date, new: bool = False,
              shop_here: bool = False) -> str:
    """One offer: initial, grade, New, You shop here, text, card + expiry chips, value, add."""
    max_v = ranking.offer_max_value(offer)
    g = ranking.grade(max_v)
    badges = pill(g, GRADE_TONE[g])
    if new:
        badges += pill("New", "purple")
    if shop_here:
        badges += pill("You shop here", "blue")
    action = pill("Added", "green") if offer.enrolled else (
        link(card.get("offers_url"), "Add to card") or pill("Not added", "amber"))
    initial = escape((offer.merchant_name.strip()[:1] or "?").upper())
    return (
        f'<div class="co-card co-offer"><div class="co-initial" aria-hidden="true">{initial}</div>'
        f'<div class="co-offer-main"><div><span class="co-merchant">'
        f"{escape(offer.merchant_name)}</span>{badges}</div>"
        f'<div class="co-muted">{escape(offer.offer_text)}</div>'
        f"<div>{card_chip(card)}{expiry_chip(offer.expires_on, today)}</div></div>"
        f'<div class="co-offer-side"><div class="co-upto">up to <span class="co-value">'
        f'{escape(money(max_v, False))}</span></div><div>{action}</div></div></div>'
    )


def todo_card(title: str, detail: str, url: str = "", url_label: str = "") -> str:
    return (f'<div class="co-card co-todo"><div><div class="co-title">{escape(title)}</div>'
            f'<div class="co-muted">{escape(detail)}</div></div>'
            f"<div>{link(url, url_label or 'Open')}</div></div>")


def option_card(opt: ranking.Option, card: dict, today: date, best: bool = False) -> str:
    """A card choice for a purchase: total, breakdown, offer status/expiry, warnings."""
    head = pill("Best card", "green") if best else ""
    status = ""
    if opt.offer is not None:
        status = pill(f"{opt.offer.merchant_name} offer", "blue")
        status += (pill("Offer added", "green") if opt.offer.enrolled
                  else pill("Offer not added", "amber"))
        status += expiry_chip(opt.offer.expires_on, today)
    warns = "".join(pill(w, "amber") for w in opt.warnings if w != "Offer not added to card yet")
    return (f'<div class="co-card">{head}<div><span class="co-merchant">{escape(opt.card_name)}'
            f'</span><span class="co-value">{escape(money(opt.total))}</span></div>'
            f'<div class="co-muted">{escape(opt.breakdown)}</div>'
            f"<div>{card_chip(card)}{status}{warns}</div></div>")


def month_bars(by_month: dict[str, float], color: str, label: str) -> None:
    """Monthly $ bars ("2026-09" keys), short month names, quiet axes."""
    import altair as alt
    import pandas as pd

    keys = sorted(by_month)
    df = pd.DataFrame({"Month": [date.fromisoformat(k + "-01").strftime("%b") for k in keys],
                       label: [by_month[k] for k in keys]})
    st.altair_chart(alt.Chart(df, height=220).mark_bar(
        color=color, cornerRadiusEnd=4, size=36).encode(
        x=alt.X("Month:N", title=None, sort=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{label}:Q", title=None, axis=alt.Axis(format="$,.0f", tickCount=4)),
        tooltip=["Month", alt.Tooltip(f"{label}:Q", format="$,.2f")],
    ).configure_view(stroke=None), width="stretch")


def bullet_list(items: list[str]) -> str:
    return '<ul class="co-list">' + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def mfa_box(source: str, label: str) -> None:
    """Inline security-code entry; the bank robot polls mfa_codes for it."""
    with st.form(f"mfa-{source}", clear_on_submit=True):
        code = st.text_input(f"{label} security code", max_chars=12, key=f"mfa-code-{source}")
        if st.form_submit_button("Send code", type="primary"):
            code = code.strip()
            if not re.fullmatch(r"[A-Za-z0-9]{4,12}", code):
                st.error("Enter the 4-12 digit code from your bank's text or email.")
            else:
                with session() as s:
                    s.add(MfaCode(source=source, code=code))
                st.success(f"Code sent. The {label} robot will use it within a minute or two.")
