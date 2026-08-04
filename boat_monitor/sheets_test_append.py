"""
Append one test row to Power_Log using a Google service account (Option A).

Requires:
  pip install -r boat_monitor/requirements-sheets.txt

Environment:
  GOOGLE_APPLICATION_CREDENTIALS  path to service account JSON
  GOOGLE_SHEETS_ID                spreadsheet ID from the sheet URL

Or boat_monitor/secrets.py with GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHEETS_ID.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
TAB = "Power_Log"


def _load_config():
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "").strip()
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    secrets = Path(__file__).resolve().parent / "secrets.py"
    if secrets.is_file():
        import importlib.util

        spec = importlib.util.spec_from_file_location("boat_secrets", secrets)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sheet_id = sheet_id or getattr(mod, "GOOGLE_SHEETS_ID", "")
        creds_path = creds_path or getattr(mod, "GOOGLE_SERVICE_ACCOUNT_FILE", "")

    if not sheet_id:
        raise SystemExit("Missing GOOGLE_SHEETS_ID (env or secrets.py)")
    if not creds_path or not Path(creds_path).is_file():
        raise SystemExit("Missing GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_FILE")
    return sheet_id, creds_path


def main():
    sheet_id, creds_path = _load_config()

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    row = [
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pc-test",
        "sheets_test",
        "",
        "",
        "",
        "",
        "",
        "sheets_test_append.py",
    ]

    body = {"values": [row]}
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=sheet_id,
            range=f"{TAB}!A:I",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )

    updates = result.get("updates", {})
    print("OK: appended row to", TAB)
    print("updatedRange:", updates.get("updatedRange"))
    print("updatedRows:", updates.get("updatedRows"))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
