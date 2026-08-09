#!/usr/bin/env python3
"""Print recent Power_Log / Events / Config from the boat sheet."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402


def main():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)

    def get_tab(name, cols="A:Z"):
        return (
            sheets.spreadsheets()
            .values()
            .get(spreadsheetId=sid, range=f"{name}!{cols}")
            .execute()
            .get("values", [])
        )

    pl = get_tab("Power_Log")
    hdr = pl[0] if pl else []
    idx = {h: i for i, h in enumerate(hdr)}
    print("=== Power_Log (last 30 boat-p2) ===")
    print("header:", hdr[:16])
    print("total rows:", len(pl) - 1)

    def g(row, k, default=""):
        i = idx.get(k)
        if i is None or i >= len(row):
            return default
        return row[i]

    shown = 0
    for row in reversed(pl[1:]):
        if not row:
            continue
        dev = g(row, "device", "boat-p2")
        if dev and dev != "boat-p2":
            continue
        note = g(row, "note")
        if note and len(str(note)) > 50:
            note = str(note)[:50] + "…"
        print(
            " ",
            g(row, "timestamp_utc", row[0] if row else ""),
            "| mode=%s" % g(row, "mode"),
            "| eng=%sV" % g(row, "engine_v"),
            "| house=%sV" % g(row, "house_v"),
            "| fw=%s" % g(row, "fw"),
            "| uplink=%s" % g(row, "uplink"),
            "| note=%s" % note,
        )
        shown += 1
        if shown >= 30:
            break

    print("\n=== Events (last 50; boot_ota / ota highlighted) ===")
    ev = get_tab("Events", "A:D")
    for row in ev[-50:]:
        detail = row[3] if len(row) > 3 else ""
        if len(str(detail)) > 300:
            detail = str(detail)[:300] + "…"
        evname = row[2] if len(row) > 2 else ""
        mark = " <<" if evname in ("boot_ota",) or "ota_action" in str(detail) else ""
        print(
            " ",
            row[0] if row else "",
            "|",
            evname,
            "|",
            detail,
            mark,
        )

    print("\n=== Config ===")
    for row in get_tab("Config", "A:B")[1:25]:
        if row and row[0]:
            v = row[1] if len(row) > 1 else ""
            if len(str(v)) > 70:
                v = str(v)[:70] + "…"
            print(" ", row[0], "=", v)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
