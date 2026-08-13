#!/usr/bin/env python3
"""
Purge old log rows from Google Sheet data tabs (keeps header row 1).

Typical use: drop OTA-stress / bench spam and keep post-USB operational logs.

  python3 sheets_data_purge.py --dry-run --after "Aug 12, 2026 7:30 PM"
  python3 sheets_data_purge.py --after "Aug 12, 2026 7:30 PM"
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_TABS = ("Power_Log", "Events", "GPS_Log", "V50_Bank", "Bilge_Log")


def parse_sheet_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y %I:%M:%S %p"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=PACIFIC)
        except ValueError:
            continue
    return None


def parse_cutoff(text):
    dt = parse_sheet_timestamp(text)
    if dt is None:
        raise SystemExit("Could not parse --after timestamp: %s" % text)
    return dt


def _col_letter(n):
    """0-based column index -> letter(s)."""
    n += 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def purge_tab(sheets, spreadsheet_id, tab, cutoff, dry_run):
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = None
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == tab:
            sheet_id = s["properties"]["sheetId"]
            break
    if sheet_id is None:
        print("SKIP %s (tab missing)" % tab)
        return 0, 0

    hdr = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="%s!1:1" % tab)
        .execute()
        .get("values", [[]])[0]
    )
    if not hdr:
        print("SKIP %s (no header)" % tab)
        return 0, 0

    end_col = _col_letter(max(0, len(hdr) - 1))
    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="%s!A2:%s" % (tab, end_col))
        .execute()
        .get("values", [])
    )
    total = len(rows)
    keep = []
    dropped = 0
    for row in rows:
        ts = parse_sheet_timestamp(row[0] if row else "")
        if ts is not None and ts >= cutoff:
            keep.append(row)
        else:
            dropped += 1

    print(
        "%s: %d rows -> keep %d, drop %d (cutoff %s PT)"
        % (tab, total, len(keep), dropped, cutoff.strftime("%b %d, %Y %I:%M %p"))
    )
    if dry_run:
        return total, dropped

    if dropped == 0:
        return total, 0

    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range="%s!A2:%s" % (tab, end_col),
    ).execute()

    if keep:
        sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="%s!A2" % tab,
            valueInputOption="USER_ENTERED",
            body={"values": keep},
        ).execute()

    return total, dropped


def main(argv=None):
    p = argparse.ArgumentParser(description="Purge old rows from sheet log tabs")
    p.add_argument(
        "--after",
        required=True,
        help="Keep rows on/after this Pacific timestamp (e.g. 'Aug 12, 2026 7:30 PM')",
    )
    p.add_argument(
        "--tabs",
        nargs="*",
        default=list(DEFAULT_TABS),
        help="Tabs to purge (default: log tabs, not Config)",
    )
    p.add_argument("--dry-run", action="store_true", help="Print counts only")
    args = p.parse_args(argv)

    cutoff = parse_cutoff(args.after)

    creds_path = _credentials_path()
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    spreadsheet_id = _sheet_id(creds)

    print("Spreadsheet:", spreadsheet_id)
    print("Mode:", "dry-run" if args.dry_run else "PURGE")

    grand_total = 0
    grand_drop = 0
    for tab in args.tabs:
        total, dropped = purge_tab(sheets, spreadsheet_id, tab, cutoff, args.dry_run)
        grand_total += total
        grand_drop += dropped

    print("TOTAL: %d rows scanned, %d dropped, %d kept" % (grand_total, grand_drop, grand_total - grand_drop))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
