"""Every page renders in demo mode without exceptions (headless AppTest)."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import config, db

PAGES = ["views/dashboard.py", "views/search.py", "views/cards_credits.py",
         "views/insights.py", "views/watchlist.py", "views/alerts.py", "views/accounts.py",
         "views/add.py", "views/my_cards.py", "views/get_started.py"]


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
    app.switch_page("views/search.py").run()
    app.text_input(key="search_q").input("best card for $40 at Lyft?").run()
    assert not app.exception
    html = "".join(h.proto.body for h in app.get("html"))
    assert html.index("Visa Signature") < html.index("Blue Cash Everyday")


def test_add_offer_and_card_digits(app):
    from sqlalchemy import select

    from app.config import card_by_id
    from app.db import Offer

    app.switch_page("views/add.py").run()
    app.text_input[0].input("Nike")
    app.number_input[0].set_value(10.0)
    app.number_input[1].set_value(15.0)
    app.button[0].click().run()
    assert not app.exception, app.exception
    with db.session() as s:
        nike = s.scalar(select(Offer).where(Offer.merchant_name == "Nike"))
    assert nike and nike.source == "manual" and nike.max_credit == 15

    app.switch_page("views/my_cards.py").run()
    app.text_input[1].input("4321")  # BofA (second card)
    app.button[1].click().run()
    assert not app.exception, app.exception
    assert card_by_id("bofa_ccr")["last_digits"] == "4321"


def test_login_page_comes_first(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.chdir(tmp_path)
    st.secrets._reset()
    db.set_engine(f"sqlite:///{tmp_path / 'live.db'}")
    at = AppTest.from_file("../app/streamlit_app.py", default_timeout=30)
    at.secrets["ALLOWED_EMAIL"] = "me@example.com"
    at.secrets["auth"] = {"redirect_uri": "http://localhost:8501/oauth2callback",
                          "cookie_secret": "x", "client_id": "id", "client_secret": "s",
                          "server_metadata_url": "https://accounts.google.com/.well-known/"
                                                 "openid-configuration"}
    at.run()
    assert not at.exception, at.exception
    assert [b.label for b in at.button] == ["Log in with Google"]
    assert not at.get("html") or "co-kpis" not in "".join(h.proto.body for h in at.get("html"))


def test_first_run_starts_on_get_started(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.chdir(tmp_path)
    st.secrets._reset()
    config.set_card_overrides({})
    db.set_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    st.cache_resource.clear()
    at = AppTest.from_file("../app/streamlit_app.py", default_timeout=30)
    monkeypatch.setattr("app.demo.seed", lambda s: None)  # empty account, like a new user
    at.run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Get started"
