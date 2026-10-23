"""Alerts: toggles stored in settings, quiet hours, recent sent alerts."""

import pandas as pd
import streamlit as st
from sqlalchemy import select

from app import db, refresh
from app.config import settings_config
from app.db import AlertSent

LABELS = {
    "new_high_value": "New high-value offer",
    "high_value_min": "High-value means at least ($)",
    "expiry_3day": "Offer expires in 3 days (8 AM email; again 1 day before if unused)",
    "mfa_needed": "Bank needs a security code",
    "credit_posted": "Credit posted",
    "credit_overdue": "Credit overdue",
    "rotating_reminder": "Rotating category reminder (Discover quarterly, BofA monthly)",
    "watchlist_match": "Watchlist match",
    "weekly_summary": "Weekly summary (Sunday 9 AM)",
    "monthly_recap": "Monthly recap (1st of the month)",
}
THRESHOLDS = [5, 10, 20, 50]


def hour(h: int) -> str:
    return f"{(h - 1) % 12 + 1} {'AM' if h < 12 else 'PM'}"


with db.session() as s:
    current = db.alert_settings(s)
    sent = s.scalars(select(AlertSent).order_by(AlertSent.sent_at.desc()).limit(20)).all()

st.title("Alerts")
st.caption("Channel: email to your Gmail (on).")

with st.form("alerts"):
    values = {}
    for key in settings_config()["alert_defaults"]:
        label = LABELS.get(key, key.replace("_", " ").capitalize())
        if key == "high_value_min":
            cur = current[key] if current[key] in THRESHOLDS else 20
            values[key] = st.selectbox(label, THRESHOLDS, index=THRESHOLDS.index(cur))
        else:
            values[key] = st.toggle(label, value=bool(current[key]))
    if st.form_submit_button("Save", type="primary"):
        with db.session() as s:
            db.set_setting(s, "alerts", values)
        st.success("Alert settings saved.")

q = settings_config()["quiet_hours"]
st.info(f"Quiet hours: {hour(q['start'])}–{hour(q['end'])}. Alerts are held and sent at "
        f"{hour(q['end'])}.")

st.subheader("Recently sent")
if sent:
    st.dataframe(pd.DataFrame([{"Sent": refresh.local_time(a.sent_at), "Kind": a.kind,
                                "Subject": a.subject} for a in sent]),
                 hide_index=True, width="stretch")
else:
    st.caption("No alerts sent yet.")
