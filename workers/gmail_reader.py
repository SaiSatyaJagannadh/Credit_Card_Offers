"""Gmail API: list new bank emails since the stored history_id, fetch them as text, send mail.

Tokens (authorized-user JSON) live only in secrets: GMAIL_TOKEN_JSON and optionally
GMAIL_TOKENS_JSON (a JSON list, one per account). Email bodies are never logged.
"""

import base64
import json
import logging
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import secret, settings_config
from app.db import EmailProcessed, get_setting

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/gmail.send"]
MAX_PER_RUN = 40  # ponytail: keeps a run under ~2 min; backlog drains over the next hours

log = logging.getLogger(__name__)


class GmailNotConnected(Exception):
    pass


@dataclass
class Email:
    id: str
    account: str
    sender: str  # bare address
    subject: str
    date: str  # Date header as sent
    text: str  # stripped + truncated body


def tokens() -> list[dict]:
    out = []
    if single := secret("GMAIL_TOKEN_JSON"):
        out.append(json.loads(single))
    if many := secret("GMAIL_TOKENS_JSON"):
        out += [t for t in json.loads(many) if t not in out]
    return out


def service(info: dict) -> Any:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_info(info, SCOPES)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def html_to_text(html: str, max_chars: int | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    return text[: max_chars or settings_config()["llm"]["max_chars"]]


def is_bank(sender: str) -> bool:
    domain = parseaddr(sender)[1].rpartition("@")[2].lower()
    return any(domain == d or domain.endswith("." + d) for d in settings_config()["bank_senders"])


def sender_query() -> str:
    return "from:(" + " OR ".join(settings_config()["bank_senders"]) + ")"


def _paged(call: Any, key: str, **kw: Any) -> list[dict]:
    out, token = [], None
    while True:
        r = call(userId="me", pageToken=token, **kw).execute()
        out += r.get(key, [])
        if not (token := r.get("nextPageToken")):
            return out


def list_new(s: Session, svc: Any) -> tuple[str, list[str], str]:
    """(account email, unprocessed message ids, history_id to store once they're done)."""
    from googleapiclient.errors import HttpError

    profile = svc.users().getProfile(userId="me").execute()
    account, hid = profile["emailAddress"], profile["historyId"]
    # Bank senders only (pre-filter in the query), then narrowed to messages added since the
    # stored history_id. First run (or history_id too old): the last 30 days.
    ids = [m["id"] for m in _paged(svc.users().messages().list, "messages",
                                   q=f"{sender_query()} newer_than:30d")]
    if since := get_setting(s, f"gmail_history_id:{account}"):
        try:
            hist = _paged(svc.users().history().list, "history", startHistoryId=since,
                          historyTypes=["messageAdded"])
            added = {a["message"]["id"] for h in hist for a in h.get("messagesAdded", [])}
            ids = [i for i in ids if i in added]
        except HttpError as e:
            if e.resp.status != 404:  # 404 = history_id expired -> keep the 30-day list
                raise
    ids = [i for i in dict.fromkeys(reversed(ids)) if not s.get(EmailProcessed, i)]
    return account, ids, hid


def _body(payload: dict) -> tuple[str, str]:
    """(mime type, decoded text) preferring text/html, else text/plain."""
    found: dict[str, str] = {}
    stack = [payload]
    while stack:
        p = stack.pop()
        stack += p.get("parts", [])
        mime, data = p.get("mimeType", ""), p.get("body", {}).get("data")
        if data and mime in ("text/html", "text/plain") and mime not in found:
            found[mime] = base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
    if "text/html" in found:
        return "text/html", found["text/html"]
    return "text/plain", found.get("text/plain", "")


def get_email(svc: Any, message_id: str, account: str) -> Email | None:
    """Fetch one message; None if it's not from a bank sender (it goes nowhere)."""
    msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    sender = parseaddr(headers.get("from", ""))[1]
    if not is_bank(sender):
        return None
    _, body = _body(msg["payload"])
    return Email(message_id, account, sender, headers.get("subject", ""),
                 headers.get("date", ""), html_to_text(body))


def send_email(to: str, subject: str, html: str, text: str) -> None:
    """multipart/alternative via gmail.send with the first token."""
    toks = tokens()
    if not toks:
        raise GmailNotConnected("Gmail not connected — add GMAIL_TOKEN_JSON")
    msg = MIMEMultipart("alternative")
    msg["To"], msg["Subject"] = to, subject
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service(toks[0]).users().messages().send(userId="me", body={"raw": raw}).execute()
    log.info("sent email: %s", subject)
