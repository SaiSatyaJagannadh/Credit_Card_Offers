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
def _yaml_cards() -> list[dict]:
    return yaml.safe_load((CONFIG_DIR / "cards.yaml").read_text())["cards"]


_overrides: dict[str, dict] = {}


def set_card_overrides(overrides: dict[str, dict]) -> None:
    """Edits from the My cards page (DB setting "card_overrides") layered over cards.yaml.
    Callers load them once per run/rerun: app entry and workers."""
    global _overrides
    _overrides = overrides or {}
    _merged.cache_clear()


def _merge(card: dict, o: dict) -> dict:
    out = {**card, **{k: v for k, v in o.items() if k not in ("categories", "rotating")}}
    out["categories"] = {**card.get("categories", {}), **o.get("categories", {})}
    if card.get("rotating") is not None or "rotating" in o:
        out["rotating"] = {**(card.get("rotating") or {}), **o.get("rotating", {})}
    return out


@cache
def _merged() -> tuple[dict, ...]:
    return tuple(_merge(c, _overrides.get(c["id"], {})) for c in _yaml_cards())


def cards_config() -> list[dict]:
    return list(_merged())


@cache
def settings_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text())


def card_by_id(card_id: str) -> dict:
    return next(c for c in cards_config() if c["id"] == card_id)


def tz() -> ZoneInfo:
    return ZoneInfo(settings_config()["timezone"])
