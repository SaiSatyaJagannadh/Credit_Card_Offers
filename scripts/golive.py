"""One-shot go-live: python scripts/golive.py

Asks for each value once (keys hidden), then:
  1. writes .streamlit/secrets.toml (gitignored) — paste the same file into Streamlit Cloud
  2. creates the DB tables (alembic upgrade head)
  3. gets the Gmail token from credentials.json if you don't have one yet
  4. sets the GitHub Actions secrets with `gh` (run `gh auth login` first)
Re-run any time; existing values in secrets.toml are offered as defaults.
"""

import getpass
import json
import os
import secrets
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
PY = sys.executable
REPO = "SaiSatyaJagannadh/Credit_Card_Offers"
GH_KEYS = ["DATABASE_URL", "LLM_PROVIDER", "LLM_MODEL", "OPENAI_API_KEY", "NVIDIA_API_KEY",
           "GMAIL_TOKEN_JSON", "ALLOWED_EMAIL", "ALERT_EMAIL", "APP_URL"]


def ask(old: dict, key: str, label: str, hidden: bool = False, default: str = "") -> str:
    cur = old.get(key) or default
    shown = "(saved)" if hidden and cur else cur
    prompt = f"{label}{f' [{shown}]' if shown else ''}: "
    val = (getpass.getpass(prompt) if hidden else input(prompt)).strip()
    return val or cur


def q(v: str) -> str:
    return json.dumps(v)  # TOML basic strings accept JSON string escaping


def main() -> None:
    old = tomllib.loads(SECRETS.read_text()) if SECRETS.exists() else {}
    auth_old = old.get("auth", {})
    v: dict[str, str] = {}
    print("Press Enter to keep a saved value. Leave optional ones blank.\n")
    v["DATABASE_URL"] = ask(old, "DATABASE_URL", "Supabase session pooler URL", hidden=True)
    v["ALLOWED_EMAIL"] = ask(old, "ALLOWED_EMAIL", "Your Gmail (only this email can log in)")
    v["ALERT_EMAIL"] = ask(old, "ALERT_EMAIL", "Send alerts to", default=v["ALLOWED_EMAIL"])
    v["APP_URL"] = ask(old, "APP_URL", "Streamlit app URL (https://….streamlit.app)")
    v["LLM_PROVIDER"] = ask(old, "LLM_PROVIDER", "LLM provider openai|nvidia", default="openai")
    v["LLM_MODEL"] = ask(old, "LLM_MODEL", "LLM model",
                         default="gpt-4.1-mini" if v["LLM_PROVIDER"] == "openai"
                         else "meta/llama-3.3-70b-instruct")
    key = "OPENAI_API_KEY" if v["LLM_PROVIDER"] == "openai" else "NVIDIA_API_KEY"
    v[key] = ask(old, key, f"{key}", hidden=True)
    v["GITHUB_TOKEN"] = ask(old, "GITHUB_TOKEN", "GitHub fine-grained token (Refresh now)",
                            hidden=True)
    v["GITHUB_REPO"] = REPO
    v["DEMO_MODE"] = "false"

    v["GMAIL_TOKEN_JSON"] = old.get("GMAIL_TOKEN_JSON", "")
    creds = ROOT / "credentials.json"
    if not v["GMAIL_TOKEN_JSON"] and creds.exists():
        print("\nOpening Google sign-in for Gmail (approve both permissions)…")
        out = subprocess.run([PY, "-m", "workers.gmail_setup", str(creds)], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        v["GMAIL_TOKEN_JSON"] = out.strip().splitlines()[-1]
    elif not v["GMAIL_TOKEN_JSON"]:
        print("\n(no credentials.json yet — Gmail skipped; re-run after Google step 2.3)")

    print("\nLogin (Google OAuth *Web* client):")
    auth = {
        "redirect_uri": f"{v['APP_URL'].rstrip('/')}/oauth2callback" if v["APP_URL"] else "",
        "cookie_secret": auth_old.get("cookie_secret") or secrets.token_urlsafe(32),
        "client_id": ask(auth_old, "client_id", "Web client ID"),
        "client_secret": ask(auth_old, "client_secret", "Web client secret", hidden=True),
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
    }

    lines = [f"{k} = {q(x)}" for k, x in v.items() if x]
    lines += ["", "[auth]"] + [f"{k} = {q(x)}" for k, x in auth.items()]
    SECRETS.write_text("\n".join(lines) + "\n")
    os.chmod(SECRETS, 0o600)
    print(f"\nWrote {SECRETS.relative_to(ROOT)} — paste its contents into Streamlit Cloud > "
          "Settings > Secrets.")

    if v["DATABASE_URL"]:
        print("Creating database tables…")
        env = {**os.environ, "DATABASE_URL": v["DATABASE_URL"]}
        subprocess.run([PY, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)

    gh = shutil.which("gh")
    if gh and subprocess.run([gh, "auth", "status"], capture_output=True).returncode == 0:
        for k in GH_KEYS:
            if v.get(k):
                subprocess.run([gh, "secret", "set", k, "-R", REPO], input=v[k], text=True,
                               check=True, capture_output=True)
                print(f"GitHub secret set: {k}")
    else:
        print("GitHub secrets not set: run `gh auth login`, then re-run this script.")
    if v["APP_URL"]:
        print(f"\nAdd this redirect URI to the Google Web client: {auth['redirect_uri']}")


if __name__ == "__main__":
    main()
