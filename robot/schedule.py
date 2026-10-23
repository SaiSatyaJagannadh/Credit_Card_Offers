"""Turn the Mac's automatic bank sync on/off (launchd): daily 7 AM run + Refresh-now poller."""

import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = Path.home() / "Library" / "LaunchAgents"
JOBS = {
    "com.cardoffers.robot": {"args": ["--once", "--headed"],
                             "StartCalendarInterval": {"Hour": 7, "Minute": 0}},
    "com.cardoffers.robot-poll": {"args": ["--poll", "--headed"], "KeepAlive": True,
                                  "RunAtLoad": True},
}


def _plist(label: str, job: dict) -> dict:
    extra = {k: v for k, v in job.items() if k != "args"}
    log = str(Path.home() / "Library" / "Logs" / f"{label}.log")
    return {"Label": label, "WorkingDirectory": str(ROOT),
            "ProgramArguments": [sys.executable, "-m", "robot.runner", *job["args"]],
            "StandardOutPath": log, "StandardErrorPath": log, **extra}


def is_on() -> bool:
    return all((AGENTS / f"{label}.plist").exists() for label in JOBS)


def turn_on() -> None:
    AGENTS.mkdir(parents=True, exist_ok=True)
    for label, job in JOBS.items():
        path = AGENTS / f"{label}.plist"
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        path.write_bytes(plistlib.dumps(_plist(label, job)))
        r = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or f"launchctl load failed for {label}")


def turn_off() -> None:
    for label in JOBS:
        path = AGENTS / f"{label}.plist"
        if path.exists():
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            path.unlink()
