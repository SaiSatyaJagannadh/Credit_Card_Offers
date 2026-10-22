"""MFA via the DB: robot marks needs_code, I type the code on the Accounts page."""

import logging
import time
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import delete, select

from app.db import MfaCode, SyncRun, session, utcnow

log = logging.getLogger("robot")

CODE_TTL = timedelta(minutes=10)
TIMEOUT_MSG = "No security code entered within 10 minutes — kept previous offers"


def set_status(run_id: int, status: str, message: str = "", done: bool = False) -> None:
    with session() as s:
        run = s.get(SyncRun, run_id)
        assert run is not None
        run.status, run.message = status, message
        if done:
            run.finished_at = utcnow()


def take_code(source: str) -> str | None:
    """Newest unexpired code for `source`, deleted once read. Expired codes are purged."""
    cutoff = utcnow() - CODE_TTL
    with session() as s:
        s.execute(delete(MfaCode).where(MfaCode.source == source, MfaCode.created_at < cutoff))
        row = s.scalars(select(MfaCode).where(MfaCode.source == source)
                        .order_by(MfaCode.created_at.desc())).first()
        if row is None:
            return None
        code = row.code
        s.delete(row)
        return code


def _notify(source: str) -> None:
    """Immediate email; same dedupe key as the hourly worker, so it is never sent twice."""
    try:
        from app.db import alert_settings
        from workers.alerts import mfa_alert

        with session() as s:
            if alert_settings(s).get("mfa_needed"):
                mfa_alert(s)
    except Exception as e:  # email is best-effort; the UI pill shows needs_code anyway
        log.warning("MFA email not sent (%s: %s)", source, type(e).__name__)


def wait_for_code(run_id: int, source: str, timeout: float = 600, interval: float = 5,
                  sleep: Callable[[float], None] = time.sleep) -> str | None:
    """Mark needs_code, email me, poll mfa_codes. None (and status error) on timeout."""
    set_status(run_id, "needs_code", "needs security code")
    _notify(source)
    waited = 0.0
    while True:
        if code := take_code(source):
            set_status(run_id, "running", "security code received")
            return code
        if waited >= timeout:
            set_status(run_id, "error", TIMEOUT_MSG, done=True)
            return None
        sleep(interval)
        waited += interval
