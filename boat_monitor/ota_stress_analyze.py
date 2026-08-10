#!/usr/bin/env python3
"""Mine Power_Log + Events for OTA stress timing (sheet-backed, no USB).

When ota_lifecycle / boot_ota rows exist, includes device-reported phases.
Otherwise infers upgrade windows from log gaps and remote_config lines.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _sheets():
    from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False), _sheet_id(creds)


def _parse_sheet_ts(text):
    try:
        return datetime.strptime(str(text).strip(), "%b %d, %Y %I:%M %p")
    except Exception:
        return None


def _parse_kv(detail: str) -> dict:
    out = {}
    for part in str(detail or "").split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _fw_rows():
    sheets, sid = _sheets()
    hdr = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Power_Log!1:1").execute().get("values", [[]])[0]
    idx = {h: i for i, h in enumerate(hdr)}
    rows = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Power_Log!A2:N").execute().get("values", [])
    out = []
    for row in rows:
        if len(row) > 1 and row[1] == "boat-p2":
            out.append(
                {
                    "ts": row[0],
                    "dt": _parse_sheet_ts(row[0]),
                    "fw": row[idx.get("fw", 11)] if len(row) > idx.get("fw", 11) else "",
                    "note": row[idx.get("note", 13)] if len(row) > idx.get("note", 13) else "",
                }
            )
    return out


def _ota_events():
    sheets, sid = _sheets()
    ev = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Events!A2:D").execute().get("values", [])
    ota = []
    for row in ev:
        if len(row) < 4:
            continue
        name = row[2]
        detail = row[3]
        if name in ("boot_ota", "ota_lifecycle") or "ota_action=1" in detail:
            ota.append({"ts": row[0], "dt": _parse_sheet_ts(row[0]), "event": name, "detail": detail, "kv": _parse_kv(detail)})
        elif name == "ota_trace":
            ota.append({"ts": row[0], "dt": _parse_sheet_ts(row[0]), "event": name, "detail": detail, "kv": _parse_kv(detail)})
        elif name == "device_stats":
            ota.append({"ts": row[0], "dt": _parse_sheet_ts(row[0]), "event": name, "detail": detail, "kv": _parse_kv(detail)})
    return ota


def infer_upgrades(pl_rows, since_dt=None):
    """Detect fw bumps and gap before first log on new fw."""
    upgrades = []
    prev = None
    for row in pl_rows:
        if since_dt and row["dt"] and row["dt"] < since_dt:
            prev = row
            continue
        if not prev:
            prev = row
            continue
        if row["fw"] and prev["fw"] and row["fw"] != prev["fw"]:
            gap_s = None
            if row["dt"] and prev["dt"]:
                gap_s = int((row["dt"] - prev["dt"]).total_seconds())
            upgrades.append(
                {
                    "from_fw": prev["fw"],
                    "to_fw": row["fw"],
                    "last_log_old_fw": prev["ts"],
                    "first_log_new_fw": row["ts"],
                    "inferred_ota_window_s": gap_s,
                }
            )
        prev = row
    return upgrades


def stuck_ota_signals(ota_events, since_dt=None):
    """remote_config rows: ota_action=1 while current < min_fw (possible stall)."""
    stalls = []
    for ev in ota_events:
        if ev["event"] != "remote_config":
            continue
        if since_dt and ev["dt"] and ev["dt"] < since_dt:
            continue
        kv = ev["kv"]
        if kv.get("ota_action") != "1":
            continue
        cur = kv.get("current", "")
        min_fw = kv.get("min_fw_version", "")
        if cur and min_fw and cur != min_fw:
            stalls.append({"ts": ev["ts"], "current": cur, "min_fw": min_fw})
    return stalls


def main():
    import argparse
    import json

    p = argparse.ArgumentParser()
    p.add_argument("--since", default="Aug 9, 2026 3:00 PM", help="sheet timestamp lower bound")
    args = p.parse_args()
    since_dt = _parse_sheet_ts(args.since)

    pl = _fw_rows()
    ota = _ota_events()
    lifecycle = [e for e in ota if e["event"] in ("boot_ota", "ota_lifecycle")]
    traces = [e for e in ota if e["event"] == "ota_trace"]

    report = {
        "since": args.since,
        "power_log_rows": len(pl),
        "device_ota_event_rows": len(lifecycle),
        "ota_trace_rows": len(traces),
        "ota_trace_samples": [
            {"ts": t["ts"], "detail_head": (t["detail"] or "")[:500]} for t in traces[-6:]
        ],
        "inferred_upgrades": infer_upgrades(pl, since_dt),
        "ota_action_stall_samples": stuck_ota_signals(ota, since_dt)[-20:],
        "telemetry_gap": len(lifecycle) == 0,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
