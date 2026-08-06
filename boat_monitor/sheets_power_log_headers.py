#!/usr/bin/env python3
"""Ensure Power_Log row 1 includes fw and uplink columns (in-place header update)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, TABS, _credentials_path, _sheet_id  # noqa: E402

HEADERS = TABS["Power_Log"]


def main():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_path = _credentials_path()
    if not creds_path:
        print("Missing credentials", file=sys.stderr)
        return 1

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)

    sheets.spreadsheets().values().update(
        spreadsheetId=sid,
        range="Power_Log!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [HEADERS]},
    ).execute()
    print("OK: Power_Log headers:", ", ".join(HEADERS))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
