"""Config loading: YAML files + secrets (env vars first, then Streamlit secrets)."""

import os
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def secret(name: str, default: str | None = None) -> str | None:
    """Env var first (workers, GitHub Actions), then st.secrets (Streamlit Cloud)."""
    if name in os.environ:
        return os.environ[name]
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no streamlit runtime / no secrets file
        pass
    return default


def demo_mode() -> bool:
    return (secret("DEMO_MODE", "false") or "").lower() in ("1", "true", "yes")


@cache
def cards_config() -> list[dict]:
    return yaml.safe_load((CONFIG_DIR / "cards.yaml").read_text())["cards"]


@cache
def settings_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text())


def card_by_id(card_id: str) -> dict:
    return next(c for c in cards_config() if c["id"] == card_id)


def tz() -> ZoneInfo:
    return ZoneInfo(settings_config()["timezone"])
