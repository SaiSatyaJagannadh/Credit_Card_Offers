"""One-time Gmail OAuth: python -m workers.gmail_setup [path/to/credentials.json]

Opens a browser, then prints the authorized-user token JSON. Paste it into the
GMAIL_TOKEN_JSON secret (Streamlit + GitHub Actions). Never commit it.
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from workers.gmail_reader import SCOPES


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "credentials.json"
    creds = InstalledAppFlow.from_client_secrets_file(path, SCOPES).run_local_server(
        port=0, access_type="offline", prompt="consent")
    print(creds.to_json())


if __name__ == "__main__":
    main()
