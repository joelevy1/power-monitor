#!/usr/bin/env python3
"""Rewrite Config tab to a single canonical row per key (no empty cmd_* dupes)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402

# Keys to drop entirely (legacy / backup / empty one-shots).
DROP_KEYS = frozenset(
    {
        "cmd_ota",
        "cmd_reboot",
        "boat-p2:cmd_ota",
        "boat-p2:cmd_reboot",
        "boat-p2:v50_capacity_wh",
        "v50_capacity_wh",
        "wifi_networks_backup",
        "force_ota",
        "force_reboot",
    }
)

# Prefer device-scoped value when both `key` and `boat-p2:key` exist.
DEVICE = "boat-p2"

CANONICAL_ORDER = [
    "interval_engine_off_s",
    "interval_engine_on_s",
    "min_fw_version",
    "wifi_networks",
    f"{DEVICE}:v50_capacity_mah",
    f"{DEVICE}:v50_full_at_utc",
]


def main():
    creds_path = _credentials_path()
    if not creds_path:
        print("Missing credentials", file=sys.stderr)
        return 1

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)

    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=sid, range="Config!A2:D500")
        .execute()
        .get("values", [])
    )

    by_key: dict[str, list] = {}
    for row in rows:
        if not row or not str(row[0]).strip():
            continue
        key = str(row[0]).strip()
        if key in DROP_KEYS:
            continue
        val = row[1] if len(row) > 1 else ""
        note = row[3] if len(row) > 3 else (row[2] if len(row) > 2 and ":" not in str(row[2]) else "")
        if str(val).strip() == "" and key.startswith("cmd_"):
            continue
        by_key[key] = [key, val, note]

    # Merge global into device-scoped where applicable.
    for base in ("v50_capacity_mah", "v50_full_at_utc"):
        scoped = f"{DEVICE}:{base}"
        if base in by_key and scoped not in by_key:
            by_key[scoped] = [scoped, by_key[base][1], by_key.pop(base)[2] or "migrated from global key"]
        elif base in by_key and scoped in by_key:
            del by_key[base]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = [["key", "value", "updated_utc", "note"]]
    seen = set()
    for key in CANONICAL_ORDER:
        if key in by_key:
            k, v, n = by_key[key]
            out.append([k, v, now, n or ""])
            seen.add(key)
    for key in sorted(by_key.keys()):
        if key in seen:
            continue
        k, v, n = by_key[key]
        out.append([k, v, now, n or ""])

    sheets.spreadsheets().values().clear(spreadsheetId=sid, range="Config!A2:D500").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=sid,
        range="Config!A1",
        valueInputOption="USER_ENTERED",
        body={"values": out},
    ).execute()

    print("OK: Config cleaned — %d data rows" % (len(out) - 1))
    for row in out[1:]:
        val = str(row[1])
        if len(val) > 50:
            val = val[:47] + "..."
        print(" ", row[0], "=", val)
    return 0


if __name__ == "__main__":
    sys.exit(main())
