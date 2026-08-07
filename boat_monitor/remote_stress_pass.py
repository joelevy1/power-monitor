#!/usr/bin/env python3
"""
Remote stress pass for boat-p2 — drives Config tab tests and polls Power_Log / Events.

Run from cloud agent: python3 remote_stress_pass.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402
from sheets_config_upsert import upsert_config_keys  # noqa: E402


def _sheets():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False), _sheet_id(creds)


def _power_log_tail(n=15):
    sheets, sid = _sheets()
    hdr = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Power_Log!1:1").execute().get("values", [[]])[0]
    idx = {h: i for i, h in enumerate(hdr)}
    vals = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Power_Log!A2:Z").execute().get("values", [])
    rows = []
    for row in vals[-n:]:
        rows.append(
            {
                "ts": row[0] if row else "",
                "fw": row[idx.get("fw", 11)] if len(row) > idx.get("fw", 11) else "",
                "uplink": row[idx.get("uplink", 12)] if len(row) > idx.get("uplink", 12) else "",
                "note": row[idx.get("note", 13)] if len(row) > idx.get("note", 13) else "",
            }
        )
    return len(vals), rows


def _events_tail(n=10):
    sheets, sid = _sheets()
    ev = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Events!A2:D").execute().get("values", [])
    return ev[-n:]


def _stall_count():
    sheets, sid = _sheets()
    ev = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Events!A2:D").execute().get("values", [])
    return sum(1 for r in ev if len(r) > 2 and r[2] == "standby_stall_reboot")


def _wait_for_new_log(baseline_rows, timeout_s=720, label=""):
    start = time.time()
    last_ts = None
    while time.time() - start < timeout_s:
        count, rows = _power_log_tail(3)
        if count > baseline_rows:
            last = rows[-1]
            print("[%s] NEW LOG %s fw=%s uplink=%s (+%ds)" % (label, last["ts"], last["fw"], last["uplink"], int(time.time() - start)))
            return True, last
        if rows and rows[-1]["ts"] != last_ts:
            last_ts = rows[-1]["ts"]
        time.sleep(30)
    print("[%s] TIMEOUT no new log in %ds (rows still %d)" % (label, timeout_s, baseline_rows))
    return False, None


def _config(*triples):
    sheets, sid = _sheets()
    upsert_config_keys(sheets, sid, list(triples))
    for k, v, n in triples:
        print("CONFIG", k, "=", (v[:40] + "…") if len(str(v)) > 40 else v)


def _phase(name):
    print("\n" + "=" * 60)
    print("PHASE:", name, datetime.now(timezone.utc).strftime("%H:%M:%SZ"))
    print("=" * 60)
    count, rows = _power_log_tail(5)
    print("Power_Log rows=%d last=%s %s %s" % (count, rows[-1]["ts"] if rows else "?", rows[-1]["fw"] if rows else "", rows[-1]["uplink"] if rows else ""))
    return count


def main():
    results = []

    # Restore production interval; use 120s only during stress window if needed
    _config(
        ("interval_engine_off_s", "300", "stress pass: docked cadence"),
        ("interval_engine_on_s", "300", "stress pass"),
        ("min_fw_version", "1.1.39", "stress pass: match deployed fw"),
    )

    # --- 1 Remote reboot ---
    base = _phase("1 remote reboot (cmd_reboot)")
    _config(("boat-p2:cmd_reboot", "1", "stress: reboot after next log"))
    ok, row = _wait_for_new_log(base, timeout_s=480, label="reboot")
    results.append(("cmd_reboot recovery", ok))
    time.sleep(330)
    base2, _ = _power_log_tail(1)
    ok2, _ = _wait_for_new_log(base2, timeout_s=420, label="post-reboot cadence")
    results.append(("post-reboot 2nd log", ok2))

    # --- 2 Cellular fallback (bad Wi-Fi list) ---
    base = _phase("2 cellular fallback")
    _config(
        (
            "wifi_networks",
            "stress-invalid-ssid|wrong-password-only",
            "stress: force Wi-Fi miss -> cellular once",
        ),
    )
    ok, row = _wait_for_new_log(base, timeout_s=600, label="cellular")
    cell_ok = row and row.get("uplink") == "cellular"
    results.append(("cellular uplink seen", ok and cell_ok))
    if row:
        print("  uplink was:", row.get("uplink"))

    # --- 3 Restore Wi-Fi ---
    base = _phase("3 restore Wi-Fi networks")
    # Levy-Guest + Seattle Boat from wifi_known_networks (same as GitHub OTA list)
    try:
        import wifi_known_networks

        lines = []
        for ssid, pw in wifi_known_networks.WIFI_NETWORKS:
            lines.append("%s|%s" % (ssid, pw))
        wifi_text = "\n".join(lines)
    except Exception as exc:
        print("wifi_known_networks import failed:", exc)
        wifi_text = "Levy-Guest|guest\nSeattle Boat|boat"
    _config(("wifi_networks", wifi_text, "stress: restore marina Wi-Fi list"))
    ok, row = _wait_for_new_log(base, timeout_s=600, label="wifi-restore")
    wifi_ok = row and row.get("uplink") not in (None, "", "cellular")
    results.append(("Wi-Fi uplink restored", ok and wifi_ok))

    # --- 4 Wi-Fi-only stretch (modem should stay off) ---
    base = _phase("4 Wi-Fi-only watch (3 intervals)")
    time.sleep(620)
    count, rows = _power_log_tail(6)
    wifi_only = all(r.get("uplink") not in ("cellular", "") for r in rows[-3:])
    results.append(("3x Levy-Guest only", wifi_only))
    for r in rows[-3:]:
        print(" ", r["ts"], r["uplink"])

    # --- 5 Boot OTA one-shot ---
    base = _phase("5 boot OTA (cmd_ota)")
    _config(("boat-p2:cmd_ota", "1", "stress: boot-time OTA (already at version)"))
    ok, row = _wait_for_new_log(base, timeout_s=480, label="pre-ota")
    time.sleep(120)
    ok, row = _wait_for_new_log(base, timeout_s=900, label="post-ota recovery")
    results.append(("OTA cmd recovery <=15m", ok))
    if row:
        results.append(("fw still 1.1.39", row.get("fw") == "1.1.39"))

    # --- 6 Final stability ---
    base = _phase("6 final stability wait")
    time.sleep(620)
    count2, rows = _power_log_tail(4)
    results.append(("final new rows", count2 > count))

    print("\n" + "=" * 60)
    print("STRESS PASS SUMMARY")
    print("stall_reboot events total:", _stall_count())
    for name, ok in results:
        print(" ", "PASS" if ok else "FAIL", name)
    print("=" * 60)
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
