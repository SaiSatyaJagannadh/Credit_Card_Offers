"""python -m workers.run_hourly — Gmail -> extract -> match -> credit watchdog -> alerts."""

import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import update

from app import insights
from app.db import RefreshRequest, SyncRun, session, set_setting, sync_cards, utcnow
from workers import alerts, extract, gmail_reader, match

log = logging.getLogger("workers.run_hourly")


def sync_gmail() -> tuple[int, int]:
    """(emails processed, emails left for the next run)."""
    toks = gmail_reader.tokens()
    if not toks:
        raise gmail_reader.GmailNotConnected(
            "Gmail not connected — add GMAIL_TOKEN_JSON (see Accounts page)")
    done = left = 0
    for info in toks:
        svc = gmail_reader.service(info)
        with session() as s:
            account, ids, hid = gmail_reader.list_new(s, svc)
        left += max(len(ids) - gmail_reader.MAX_PER_RUN, 0)
        for mid in ids[: gmail_reader.MAX_PER_RUN]:
            with session() as s:  # one commit per email: cache + matched rows together
                e = gmail_reader.get_email(svc, mid, account)
                if e is None:
                    continue
                c = extract.extract(s, e.id, account, e.sender, e.subject, e.date, e.text)
                if c:
                    match.apply(s, e.sender, c, e.id)
                done += 1
        if len(ids) <= gmail_reader.MAX_PER_RUN:  # only advance once the backlog is done
            with session() as s:
                set_setting(s, f"gmail_history_id:{account}", hid)
    return done, left


def error_message(e: Exception) -> str:
    from google.auth.exceptions import RefreshError

    if isinstance(e, RefreshError) or "invalid_grant" in str(e):
        return "Gmail token expired — reconnect on Accounts page"
    if isinstance(e, gmail_reader.GmailNotConnected):
        return str(e)
    return f"{type(e).__name__}: {e}"


def main(now: datetime | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    now = now or datetime.now(UTC)
    with session() as s:
        sync_cards(s)
        run = SyncRun(source="gmail")
        s.add(run)
        s.flush()
        run_id = run.id
    status, msg = "ok", ""
    try:
        done, left = sync_gmail()
        msg = f"{done} emails" + (f", {left} queued for next run" if left else "")
    except Exception as e:
        status, msg = "error", error_message(e)
        expected = isinstance(e, gmail_reader.GmailNotConnected) or msg.startswith("Gmail token")
        log.error(msg, exc_info=not expected)  # no traceback for known, user-fixable errors
    # Robot offers need expiry, watchdog and alerts even when Gmail reading is off or broken.
    try:
        with session() as s:
            match.expire_offers(s)
            insights.create_expected_credits(s)
            insights.update_expected_credits(s)
            sent = alerts.check(s, now)
        msg += f", {len(sent)} alerts sent"
    except Exception as e:
        status = "error"
        msg += f"; alerts failed: {error_message(e)}"
        log.exception("alerts failed")
    with session() as s:
        r = s.get(SyncRun, run_id)
        r.status, r.message, r.finished_at = status, msg, utcnow()
        s.execute(update(RefreshRequest).where(RefreshRequest.source.in_(("all", "gmail")),
                                               RefreshRequest.done_at.is_(None))
                  .values(done_at=utcnow()))
    log.info("gmail sync %s: %s", status, msg)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
