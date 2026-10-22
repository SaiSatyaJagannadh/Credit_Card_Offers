# Home robot scheduling

Two jobs: a daily 7 AM run (`--once`) and an always-on poller (`--poll`, checks
`refresh_requests` every 2 minutes for the "Refresh now" button).

Placeholders: `REPO_PATH` = absolute path of this repo, `VENV_PY` = `REPO_PATH/.venv/bin/python`
(Windows: `REPO_PATH\.venv\Scripts\python.exe`), `DATABASE_URL_HERE` = the Supabase URL.

First, once per bank: `VENV_PY -m robot.setup amex` (saves the login to the OS keychain and
optionally opens the browser so you can log in and trust the device). Test with
`VENV_PY -m robot.runner --once --bank amex --headed`.

## macOS (launchd)

Edit both plists (replace `REPO_PATH`; set `DATABASE_URL_HERE`, or delete the
`EnvironmentVariables` block if `.streamlit/secrets.toml` already has `DATABASE_URL`), then:

```sh
cp scripts/robot/com.cardoffers.robot*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cardoffers.robot.plist
launchctl load ~/Library/LaunchAgents/com.cardoffers.robot-poll.plist
tail -f /tmp/com.cardoffers.robot*.log
```

Use a LaunchAgent (not a LaunchDaemon) so the robot can read your login keychain. A sleeping
Mac runs the 7 AM job on wake.

## Linux (cron)

```cron
DATABASE_URL=DATABASE_URL_HERE
0 7 * * *  cd REPO_PATH && VENV_PY -m robot.runner --once >> /tmp/card-offers-robot.log 2>&1
@reboot    cd REPO_PATH && VENV_PY -m robot.runner --poll >> /tmp/card-offers-poll.log 2>&1
```

## Windows (Task Scheduler)

Set `DATABASE_URL` as a user environment variable (`setx DATABASE_URL "DATABASE_URL_HERE"`), then:

```bat
schtasks /Create /TN "CardOffers Robot" /SC DAILY /ST 07:00 /TR "cmd /c cd /d REPO_PATH && VENV_PY -m robot.runner --once"
schtasks /Create /TN "CardOffers Robot Poll" /SC ONLOGON /TR "cmd /c cd /d REPO_PATH && VENV_PY -m robot.runner --poll"
```

If the daily run and a refresh overlap, the second browser can't open the same profile and
that run records an error; the next run picks up normally.
