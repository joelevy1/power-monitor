#!/usr/bin/env python3
"""Ensure Power_Log row 1 matches sheets_bootstrap TABS (incl. v50_a, fw, uplink).

If rows were logged before v50_a existed, fw/uplink were one column left; this
script inserts a blank v50_a cell when column I still holds a firmware version.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, TABS, _credentials_path, _sheet_id  # noqa: E402

HEADERS = TABS["Power_Log"]
FW_RE = re.compile(r"^\d+\.\d+\.\d+")


def migrate_v50_a_column(sheets, spreadsheet_id):
    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Power_Log!A2:L5000")
        .execute()
        .get("values", [])
    )
    if not rows:
        return 0

    fixed = 0
    out = []
    for row in rows:
        r = list(row)
        if len(r) >= 9 and FW_RE.match(str(r[8]).strip()):
            r.insert(8, "")
            fixed += 1
        while len(r) < len(HEADERS):
            r.append("")
        out.append(r[: len(HEADERS)])

    if fixed:
        sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="Power_Log!A2",
            valueInputOption="USER_ENTERED",
            body={"values": out},
        ).execute()
    return fixed


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

    shifted = migrate_v50_a_column(sheets, sid)
    if shifted:
        print("OK: inserted blank v50_a for %d existing row(s) (fw was shifted left)" % shifted)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
