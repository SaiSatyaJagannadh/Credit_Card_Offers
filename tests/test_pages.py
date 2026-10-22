"""Every page renders in demo mode without exceptions (headless AppTest)."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import db

PAGES = ["pages/dashboard.py", "pages/search.py", "pages/cards_credits.py",
         "pages/insights.py", "pages/watchlist.py", "pages/alerts.py", "pages/accounts.py"]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    db.set_engine(f"sqlite:///{tmp_path / 'demo.db'}")  # file: AppTest runs in another thread
    st.cache_resource.clear()
    at = AppTest.from_file("../app/streamlit_app.py", default_timeout=30)
    at.run()
    assert not at.exception
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(app, page):
    app.switch_page(page).run()
    assert not app.exception, app.exception


def test_search_best_card(app):
    app.switch_page("pages/search.py").run()
    app.text_input(key="search_q").input("best card for $40 at Lyft?").run()
    assert not app.exception
    html = "".join(h.proto.body for h in app.get("html"))
    assert html.index("Visa Signature") < html.index("Blue Cash Everyday")
