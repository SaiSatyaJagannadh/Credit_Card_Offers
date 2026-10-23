#!/bin/bash
# Double-click to open the Card Offers helper in your browser (runs only on this Mac).
# Leave this window open while you use the helper; close it when you're done.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "First run: installing (a few minutes)…"
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements-robot.txt \
    && .venv/bin/playwright install chromium || { echo "Install failed"; read -r; exit 1; }
fi
exec .venv/bin/streamlit run robot/helper_app.py --server.address 127.0.0.1 \
  --server.port 8510 --browser.gatherUsageStats false
