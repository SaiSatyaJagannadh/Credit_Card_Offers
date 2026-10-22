"""Streamlit entry: theme, login gate, demo seed, navigation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # `streamlit run app/...`

import streamlit as st  # noqa: E402

from app import db  # noqa: E402
from app.config import demo_mode, secret  # noqa: E402
from app.demo import seed  # noqa: E402
from app.ui import theme  # noqa: E402

st.set_page_config(page_title="Card Offers", layout="wide")
theme.inject()


def auth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:  # no secrets.toml at all
        return False


@st.cache_resource
def seed_demo() -> bool:
    with db.session() as s:
        seed(s)
    return True


if demo_mode() and not auth_configured():
    # Local dev only: DEMO_MODE with no [auth] section skips login entirely.
    st.sidebar.caption("Demo mode: login skipped (no [auth] section in secrets).")
elif not auth_configured():
    st.error("Login is not configured. Add an [auth] section to .streamlit/secrets.toml "
             "(see README).")
    st.stop()
else:
    if not st.user.is_logged_in:
        st.title("Card Offers")
        st.write("Sign in to see your offers.")
        st.button("Log in with Google", on_click=st.login, type="primary")
        st.stop()
    allowed = (secret("ALLOWED_EMAIL") or "").strip().lower()
    if not allowed or str(st.user.email or "").lower() != allowed:
        st.error("Not authorized")
        st.button("Log out", on_click=st.logout)
        st.stop()
    st.sidebar.button("Log out", on_click=st.logout)

if demo_mode():
    seed_demo()

st.navigation([
    st.Page("pages/dashboard.py", title="Dashboard", default=True),
    st.Page("pages/search.py", title="Search"),
    st.Page("pages/cards_credits.py", title="Cards & credits"),
    st.Page("pages/insights.py", title="Insights"),
    st.Page("pages/watchlist.py", title="Watchlist"),
    st.Page("pages/alerts.py", title="Alerts"),
    st.Page("pages/accounts.py", title="Accounts"),
]).run()
