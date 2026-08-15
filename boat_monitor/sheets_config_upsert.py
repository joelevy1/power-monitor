#!/usr/bin/env python3
"""Upsert Config tab rows without reordering the sheet (service account)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402


def upsert_config_keys(sheets, spreadsheet_id, rows):
    """rows: list of (key, value, note). Preserves existing row order."""
    result = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Config!A2:D2000")
        .execute()
        .get("values", [])
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pending = {k: (v, n) for k, v, n in rows}
    key_to_idx = {}
    for idx, row in enumerate(result):
        if row and row[0]:
            key_to_idx[str(row[0]).strip()] = idx

    data = []
    for key, (value, note) in list(pending.items()):
        if key in key_to_idx:
            row_num = key_to_idx[key] + 2
            data.append(
                {
                    "range": "Config!B%d:D%d" % (row_num, row_num),
                    "values": [[value, now, note]],
                }
            )
            del pending[key]

    if data:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()

    for key, (value, note) in pending.items():
        sheets.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Config!A:D",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [[key, value, now, note]]},
        ).execute()


def main(argv):
    if len(argv) < 2 or len(argv[1:]) % 3 != 0:
        print("Usage: sheets_config_upsert.py key value note [key value note ...]", file=sys.stderr)
        return 1

    creds_path = _credentials_path()
    if not creds_path:
        print("Missing service account credentials", file=sys.stderr)
        return 1

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    spreadsheet_id = _sheet_id(creds)

    triples = []
    args = argv[1:]
    for i in range(0, len(args), 3):
        triples.append((args[i], args[i + 1], args[i + 2]))

    upsert_config_keys(sheets, spreadsheet_id, triples)
    try:
        from sheets_config_policy import dedupe_config_keys

        dupes, deleted = dedupe_config_keys(sheets, spreadsheet_id)
        if dupes and deleted:
            print("OK: deduped Config after upsert (%d row(s): %s)" % (deleted, ", ".join(sorted(dupes.keys()))))
    except Exception as exc:
        print("WARN: config dedupe after upsert:", exc)
    for key, value, _ in triples:
        print("OK:", key, "=", value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
