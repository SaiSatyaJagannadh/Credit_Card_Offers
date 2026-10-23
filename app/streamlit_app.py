"""Streamlit entry: theme, login gate, demo seed, navigation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # `streamlit run app/...`

import streamlit as st  # noqa: E402

from app import db, setup_status  # noqa: E402
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


HIDE_CHROME = "<style>[data-testid=stSidebar], [data-testid=stSidebarCollapsedControl] " \
              "{display: none;}</style>"


def gate(title: str, body: str, action: str | None = None, note: str = "") -> None:
    """Centered login card shown before anything else; nothing inside loads until it passes."""
    st.markdown(HIDE_CHROME, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid, st.container(border=True, key="card-login"):
        st.title("Card Offers")
        st.subheader(title)
        st.write(body)
        if action == "login":
            st.button("Log in with Google", on_click=st.login, type="primary",
                      width="stretch")
        elif action == "logout":
            st.button("Log out and try another account", on_click=st.logout,
                      type="primary", width="stretch")
        if note:
            st.caption(note)
    st.stop()


if demo_mode() and not auth_configured():
    # Local dev only: DEMO_MODE with no [auth] section skips login entirely.
    st.sidebar.caption("Demo mode: login skipped (no [auth] section in secrets).")
elif not auth_configured():
    gate("Login isn't set up yet",
         "Add the Google login keys (the [auth] section) to this app's Streamlit secrets, "
         "then reload this page.")
else:
    allowed = (secret("ALLOWED_EMAIL") or "").strip().lower()
    if not getattr(st.user, "is_logged_in", False):
        gate("Sign in", "Your offers, which card to use, and a heads-up before offers "
             "expire. Only the owner's Google account can sign in.", "login",
             "Google may say the app isn't verified, because it's your own app. Choose "
             "Advanced, then Go to Card Offers.")
    email = str(st.user.email or "").lower()
    if not allowed:
        gate("Owner email missing", "Add ALLOWED_EMAIL (your Gmail address) to this app's "
             "Streamlit secrets, then reload.", "logout")
    if email != allowed:
        gate("This account can't open Card Offers",
             f"You signed in as {email or 'an account without an email'}. Only the owner's "
             "account is allowed. Log out, then sign in with the owner's Google account.",
             "logout")
    st.sidebar.caption(f"Signed in as {email}")
    st.sidebar.button("Log out", on_click=st.logout)

if demo_mode():
    seed_demo()
with db.session() as s:
    db.load_card_overrides(s)  # My cards edits, fresh on every rerun
    first_run = setup_status.first_run(s)

get_started = st.Page("views/get_started.py", title="Get started", default=first_run)
pages = {
    "Offers": [
        st.Page("views/dashboard.py", title="Dashboard", default=not first_run),
        st.Page("views/search.py", title="Best card / Ask"),
        st.Page("views/insights.py", title="Insights"),
        st.Page("views/cards_credits.py", title="Cards & credits"),
    ],
    "Enter details": [
        st.Page("views/add.py", title="Add & edit"),
        st.Page("views/my_cards.py", title="My cards"),
        st.Page("views/watchlist.py", title="Watchlist"),
    ],
    "Settings": [
        st.Page("views/accounts.py", title="Accounts"),
        st.Page("views/alerts.py", title="Alerts"),
    ],
}
pages = {"Start here": [get_started], **pages} if first_run else {
    **pages, "Help": [get_started]}
st.navigation(pages).run()
