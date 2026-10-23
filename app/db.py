"""SQLAlchemy 2.x models + session. Postgres (Supabase) in prod, SQLite locally.

Money is stored as Float: values here are offer/reward estimates, not a ledger,
and are rounded to cents at display time.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import secret


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC everywhere


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # slug from cards.yaml
    name: Mapped[str] = mapped_column(String(100))
    issuer: Mapped[str] = mapped_column(String(60))
    last_digits: Mapped[str] = mapped_column(String(5), default="")
    offers_program: Mapped[str | None] = mapped_column(String(60))


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)  # canonical
    category: Mapped[str] = mapped_column(String(40), default="other")


class MerchantAlias(Base):
    __tablename__ = "merchant_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(200), unique=True)  # normalized raw text
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True)
    issuer: Mapped[str] = mapped_column(String(60))
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"))
    merchant_name: Mapped[str] = mapped_column(String(120))
    offer_text: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(10))  # pct | fixed | points
    pct: Mapped[float | None] = mapped_column(Float)  # 20 means 20%
    fixed_amount: Mapped[float | None] = mapped_column(Float)
    min_spend: Mapped[float | None] = mapped_column(Float)
    max_credit: Mapped[float | None] = mapped_column(Float)
    expires_on: Mapped[date | None] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(10), default="both")  # online|in_store|both
    exclusions: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(10))  # email | robot | demo
    source_ref: Mapped[str | None] = mapped_column(String(200))  # message_id / payload id
    enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|expired|used
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"))
    merchant_raw: Mapped[str] = mapped_column(String(200))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"))
    amount: Mapped[float] = mapped_column(Float)
    date: Mapped[date] = mapped_column(Date)
    source_message_id: Mapped[str | None] = mapped_column(String(200), unique=True)


class Credit(Base):
    __tablename__ = "credits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"))
    merchant_raw: Mapped[str] = mapped_column(String(200))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"))
    amount: Mapped[float] = mapped_column(Float)
    date: Mapped[date] = mapped_column(Date)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"))
    source_message_id: Mapped[str | None] = mapped_column(String(200), unique=True)


class ExpectedCredit(Base):
    __tablename__ = "expected_credits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), unique=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    amount: Mapped[float] = mapped_column(Float)
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="waiting")  # waiting|posted|overdue
    credit_id: Mapped[int | None] = mapped_column(ForeignKey("credits.id"))


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # gmail | amex | bofa | wellsfargo
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")
    # running | ok | error | needs_code
    message: Mapped[str] = mapped_column(Text, default="")


class RefreshRequest(Base):
    __tablename__ = "refresh_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="all")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)


class MfaCode(Base):
    __tablename__ = "mfa_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RawPayload(Base):
    __tablename__ = "raw_payloads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    payload: Mapped[str] = mapped_column(Text)


class EmailProcessed(Base):
    __tablename__ = "emails_processed"
    message_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    account: Mapped[str] = mapped_column(String(200), default="")
    type: Mapped[str] = mapped_column(String(30), default="other")
    status: Mapped[str] = mapped_column(String(20))  # ok | needs_review | skipped | error
    result_json: Mapped[str] = mapped_column(Text, default="")  # LLM cache
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AlertSent(Base):
    __tablename__ = "alerts_sent"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Watchlist(Base):
    __tablename__ = "watchlist"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TodoDone(Base):
    __tablename__ = "todos_done"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    done_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON


def database_url() -> str:
    url = secret("DATABASE_URL") or "sqlite:///card_offers.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgresql") and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


_engine = None
_Session: sessionmaker[Session] | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
        _Session = sessionmaker(_engine, expire_on_commit=False)
        if _engine.dialect.name == "sqlite":
            Base.metadata.create_all(_engine)  # local dev; Postgres uses Alembic
    return _engine


def set_engine(url: str) -> None:
    """Point the app at another DB (tests use sqlite:///:memory:)."""
    global _engine, _Session
    _engine = create_engine(url)
    _Session = sessionmaker(_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)


@contextmanager
def session() -> Iterator[Session]:
    engine()
    assert _Session is not None
    with _Session() as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise


def get_setting(s: Session, key: str, default: Any = None) -> Any:
    row = s.get(Setting, key)
    return json.loads(row.value) if row else default


def set_setting(s: Session, key: str, value: Any) -> None:
    s.merge(Setting(key=key, value=json.dumps(value)))


def alert_settings(s: Session) -> dict:
    from app.config import settings_config

    return {**settings_config()["alert_defaults"], **get_setting(s, "alerts", {})}


def load_card_overrides(s: Session) -> None:
    from app.config import set_card_overrides

    set_card_overrides(get_setting(s, "card_overrides", {}))


def sync_cards(s: Session) -> None:
    """Upsert cards from cards.yaml."""
    from app.config import cards_config

    load_card_overrides(s)
    for c in cards_config():
        s.merge(
            Card(
                id=c["id"],
                name=c["name"],
                issuer=c["issuer"],
                last_digits=str(c.get("last_digits") or ""),
                offers_program=c.get("offers_program"),
            )
        )


def latest_sync(s: Session, source: str) -> SyncRun | None:
    return s.scalars(
        select(SyncRun).where(SyncRun.source == source).order_by(SyncRun.started_at.desc())
    ).first()
