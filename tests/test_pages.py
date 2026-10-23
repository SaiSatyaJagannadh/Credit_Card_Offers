"""Every page renders in demo mode without exceptions (headless AppTest)."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import config, db

PAGES = ["pages/dashboard.py", "pages/search.py", "pages/cards_credits.py",
         "pages/insights.py", "pages/watchlist.py", "pages/alerts.py", "pages/accounts.py",
         "pages/add.py", "pages/my_cards.py"]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.chdir(tmp_path)  # ignore a real .streamlit/secrets.toml in the repo
    st.secrets._reset()  # ...including one an earlier test already loaded
    config.set_card_overrides({})
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


def test_add_offer_and_card_digits(app):
    from sqlalchemy import select

    from app.config import card_by_id
    from app.db import Offer

    app.switch_page("pages/add.py").run()
    app.text_input[0].input("Nike")
    app.number_input[0].set_value(10.0)
    app.number_input[1].set_value(15.0)
    app.button[0].click().run()
    assert not app.exception, app.exception
    with db.session() as s:
        nike = s.scalar(select(Offer).where(Offer.merchant_name == "Nike"))
    assert nike and nike.source == "manual" and nike.max_credit == 15

    app.switch_page("pages/my_cards.py").run()
    app.text_input[1].input("4321")  # BofA (second card)
    app.button[1].click().run()
    assert not app.exception, app.exception
    assert card_by_id("bofa_ccr")["last_digits"] == "4321"
