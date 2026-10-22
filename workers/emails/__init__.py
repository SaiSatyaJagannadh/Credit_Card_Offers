"""Alert email templates: inline-CSS HTML + plain-text parts. Every value goes through esc()."""

import html
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

ACCENT = "#0B6E4F"
FONT = "font-family:Manrope,Helvetica,Arial,sans-serif;"
MONO = "font-family:'JetBrains Mono',Menlo,Consolas,monospace;"


def esc(v: object) -> str:
    return html.escape(str(v), quote=True)


def money(v: float | None) -> str:
    return f"${v or 0:,.2f}".replace(".00", "")


@dataclass
class ExpiringOffer:
    merchant: str
    offer_text: str
    card_name: str
    bank: str  # issuer, for "Add on <bank>"
    offers_url: str | None
    expires_on: date
    days_left: int
    max_value: float
    enrolled: bool
    spend_for_full: float | None


@dataclass
class CreditWatch:
    merchant: str
    amount: float
    purchase_date: date
    due_on: date
    status: str


def calendar_link(title: str, on: date, details: str = "") -> str:
    q = urlencode({"action": "TEMPLATE", "text": title, "details": details,
                   "dates": f"{on:%Y%m%d}/{on + timedelta(days=1):%Y%m%d}"})
    return f"https://calendar.google.com/calendar/render?{q}"


def _button(label: str, url: str, primary: bool = True) -> str:
    style = (f"background:{ACCENT};color:#FFFFFF;" if primary
             else f"background:#FFFFFF;color:{ACCENT};border:1px solid {ACCENT};")
    return (f'<a href="{esc(url)}" style="{style}display:inline-block;padding:12px 18px;'
            f'border-radius:10px;text-decoration:none;font-weight:700;margin:4px 8px 4px 0;'
            f'{FONT}">{esc(label)}</a>')


def _page(title: str, body: str, app_url: str) -> str:
    base = app_url.rstrip("/")
    links = (f'<a href="{esc(base)}/" style="color:{ACCENT};">Dashboard</a> &middot; '
             f'<a href="{esc(base)}/alerts" style="color:{ACCENT};">Alert settings</a>'
             if app_url else "")
    return (f'<!doctype html><html><body style="margin:0;background:#F7F8FA;{FONT}'
            f'color:#111827;"><div style="max-width:560px;margin:0 auto;padding:24px 16px;">'
            f'<h1 style="font-size:20px;margin:0 0 16px;">{esc(title)}</h1>{body}'
            f'<p style="font-size:13px;color:#4B5563;margin-top:24px;">{links}</p>'
            f'</div></body></html>')


def _card(inner: str) -> str:
    return (f'<div style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:14px;'
            f'padding:16px;margin:0 0 16px;">{inner}</div>')


def _days(n: int) -> str:
    return "tomorrow" if n == 1 else f"in {n} days"


def expiry_email(hero: ExpiringOffer, also: list[ExpiringOffer], watch: list[CreditWatch],
                 app_url: str) -> tuple[str, str, str]:
    """The 8 AM digest: (subject, html, text)."""
    status = "added" if hero.enrolled else "unused"
    subject = (f"{hero.merchant} offer expires {_days(hero.days_left)}: "
               f"{money(hero.max_value)} back {status}")
    added = "Added to card" if hero.enrolled else "Not added yet"
    cal = calendar_link(f"Use {hero.merchant} offer ({hero.card_name})", hero.expires_on,
                        hero.offer_text)
    buttons = (_button(f"Add on {hero.bank}", hero.offers_url) if hero.offers_url else "")
    buttons += _button("Add to my calendar", cal, primary=not hero.offers_url)
    spend = (f'<p style="margin:12px 0 0;">Spend <b style="{MONO}">'
             f'{esc(money(hero.spend_for_full))}</b> at {esc(hero.merchant)} to get the full '
             f'{esc(money(hero.max_value))}.</p>'
             if hero.spend_for_full else "")
    body = (
        f'<div style="background:{ACCENT};color:#FFFFFF;border-radius:14px;padding:20px;'
        f'margin:0 0 16px;"><div style="font-size:13px;opacity:.9;">Expires '
        f'{esc(f"{hero.expires_on:%a, %b %-d}")} ({esc(_days(hero.days_left))})</div>'
        f'<div style="font-size:22px;font-weight:800;margin:6px 0;">{esc(hero.merchant)}: '
        f'<span style="{MONO}">{esc(money(hero.max_value))}</span> back</div>'
        f'<div style="font-size:15px;">{esc(hero.offer_text)}</div>'
        f'<div style="font-size:14px;margin-top:8px;">{esc(hero.card_name)} &middot; '
        f'{esc(added)}</div></div>'
        + _card(buttons + spend))
    text = [subject, "", f"{hero.merchant}: {hero.offer_text}",
            f"Expires {hero.expires_on:%a, %b %-d} ({_days(hero.days_left)})",
            f"Card: {hero.card_name} - {added}"]
    if hero.spend_for_full:
        text.append(f"Spend {money(hero.spend_for_full)} to get the full "
                    f"{money(hero.max_value)}.")
    if hero.offers_url:
        text.append(f"Add on {hero.bank}: {hero.offers_url}")
    text.append(f"Add to my calendar: {cal}")
    if also:
        rows = "".join(
            f'<tr><td style="padding:6px 0;">{esc(o.merchant)} <span style="color:#4B5563;">'
            f'&middot; {esc(o.card_name)}</span></td><td style="padding:6px 0;text-align:right;'
            f'{MONO}">{esc(money(o.max_value))}</td><td style="padding:6px 0 6px 12px;'
            f'text-align:right;color:#8A4B00;">{esc(_days(o.days_left))}</td></tr>' for o in also)
        body += _card('<h2 style="font-size:16px;margin:0 0 8px;">Also expiring soon</h2>'
                      f'<table style="width:100%;border-collapse:collapse;font-size:14px;">'
                      f'{rows}</table>')
        text += ["", "Also expiring soon:"] + [
            f"- {o.merchant} ({o.card_name}): {money(o.max_value)}, {_days(o.days_left)}"
            for o in also]
    if watch:
        rows = "".join(
            f'<li style="margin:4px 0;">{esc(w.merchant)}: <span style="{MONO}">'
            f'{esc(money(w.amount))}</span> from {esc(f"{w.purchase_date:%b %-d}")} purchase, '
            f'due {esc(f"{w.due_on:%b %-d}")} ({esc(w.status)})</li>' for w in watch)
        body += _card('<h2 style="font-size:16px;margin:0 0 8px;">Credit to watch</h2>'
                      f'<ul style="margin:0;padding-left:18px;font-size:14px;">{rows}</ul>')
        text += ["", "Credit to watch:"] + [
            f"- {w.merchant}: {money(w.amount)} from {w.purchase_date:%b %-d} purchase, "
            f"due {w.due_on:%b %-d} ({w.status})" for w in watch]
    if app_url:
        text += ["", f"Dashboard: {app_url}", f"Alerts: {app_url.rstrip('/')}/alerts"]
    return subject, _page("Offer expiring soon", body, app_url), "\n".join(text)


def simple_email(subject: str, title: str, lines: list[str], app_url: str
                 ) -> tuple[str, str, str]:
    """Generic alert: a title and a bullet list. (subject, html, text)"""
    items = "".join(f'<li style="margin:6px 0;">{esc(x)}</li>' for x in lines)
    body = _card(f'<ul style="margin:0;padding-left:18px;font-size:15px;">{items}</ul>')
    text = "\n".join([title, ""] + [f"- {x}" for x in lines]
                     + (["", f"Dashboard: {app_url}"] if app_url else []))
    return subject, _page(title, body, app_url), text


def recap_email(month: str, sections: dict[str, list[str]], totals: dict[str, float],
                app_url: str) -> tuple[str, str, str]:
    """Monthly recap: totals tiles + one list per section."""
    subject = f"Your {month} card offers recap"
    tiles = "".join(
        f'<td style="padding:8px;text-align:center;"><div style="font-size:12px;color:#4B5563;">'
        f'{esc(k)}</div><div style="font-size:20px;font-weight:800;{MONO}">{esc(money(v))}'
        f'</div></td>' for k, v in totals.items())
    body = _card(f'<table style="width:100%;"><tr>{tiles}</tr></table>')
    text = [subject, ""] + [f"{k}: {money(v)}" for k, v in totals.items()]
    for name, lines in sections.items():
        items = "".join(f'<li style="margin:4px 0;">{esc(x)}</li>' for x in lines) or (
            '<li style="color:#4B5563;">None</li>')
        body += _card(f'<h2 style="font-size:16px;margin:0 0 8px;">{esc(name)}</h2>'
                      f'<ul style="margin:0;padding-left:18px;font-size:14px;">{items}</ul>')
        text += ["", f"{name}:"] + ([f"- {x}" for x in lines] or ["- None"])
    if app_url:
        text += ["", f"Dashboard: {app_url}"]
    return subject, _page(subject, body, app_url), "\n".join(text)
