"""python -m workers.run_monthly — recap of last month (GitHub Actions on the 1st)."""

import logging
import sys
from datetime import UTC, datetime

from app import db
from app.db import session
from workers import alerts


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with session() as s:
        db.load_card_overrides(s)
        subject = alerts.monthly_recap(s, datetime.now(UTC))
    logging.info("monthly recap: %s", subject or "nothing sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
