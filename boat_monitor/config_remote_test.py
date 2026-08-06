#!/usr/bin/env python3
"""Set Config tab rows for a remote OTA + interval test (PC / cloud agent).

Requires GOOGLE_SHEETS_ID and service account JSON (same as sheets_bootstrap.py).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402


def upsert_config_rows(sheets, spreadsheet_id, rows):
    """rows: list of (key, value, note)"""
    result = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Config!A2:D")
        .execute()
        .get("values", [])
    )
    key_to_row = {}
    for idx, row in enumerate(result):
        if row and row[0]:
            key_to_row[str(row[0]).strip()] = idx + 2

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = []
    for key, value, note in rows:
        row_num = key_to_row.get(key)
        if row_num:
            data.append({"range": "Config!B%d:D%d" % (row_num, row_num), "values": [[value, now, note]]})
        else:
            next_row = len(result) + 2 + len([d for d in data if "A" in d.get("range", "")])
            # append new keys at bottom
            pass

    # Simpler: clear known keys area and rewrite block below header
    block = [["key", "value", "updated_utc", "note"]]
    merged = {k: (v, n) for k, v, n in rows}
    for row in result:
        if not row:
            continue
        k = str(row[0]).strip()
        if k in merged:
            v, n = merged[k]
            block.append([k, v, now, n])
            del merged[k]
        elif k:
            block.append(row + [""] * (4 - len(row)))
    for k, (v, n) in merged.items():
        block.append([k, v, now, n])

    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Config!A1",
        valueInputOption="USER_ENTERED",
        body={"values": block},
    ).execute()


def main():
    target_fw = os.environ.get("REMOTE_TEST_FW", "1.1.9")
    interval_s = os.environ.get("REMOTE_TEST_INTERVAL_S", "360")

    creds_path = _credentials_path()
    if not creds_path:
        print("Missing service account credentials", file=sys.stderr)
        return 1

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    spreadsheet_id = _sheet_id(creds)

    rows = [
        ("interval_engine_on_s", interval_s, "remote test: 6 min engine-on log cadence"),
        ("interval_engine_off_s", interval_s, "remote test: 6 min docked log cadence"),
        ("min_fw_version", target_fw, "remote test: OTA if Pico is older"),
        ("cmd_ota", "1", "remote test: one-shot OTA on next log POST"),
    ]

    # Read existing config keys and merge
    existing = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Config!A2:D500")
        .execute()
        .get("values", [])
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_key = {str(r[0]).strip(): r for r in existing if r and r[0]}
    for key, value, note in rows:
        by_key[key] = [key, value, now, note]

    out = [["key", "value", "updated_utc", "note"]]
    for key in sorted(by_key.keys()):
        row = by_key[key]
        out.append(row + [""] * (4 - len(row)))

    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Config!A1",
        valueInputOption="USER_ENTERED",
        body={"values": out},
    ).execute()

    print("OK: Config tab updated on spreadsheet", spreadsheet_id)
    print("  interval_engine_on_s / off_s =", interval_s)
    print("  min_fw_version =", target_fw)
    print("  cmd_ota = 1 (cleared by Apps Script after Pico consumes it)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
