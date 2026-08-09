#!/usr/bin/env python3
"""
OTA stress harness — ship N sequential firmware versions and measure upgrade timing.

Metrics per round (from Google Sheet Events `ota_lifecycle` + Power_Log):
  - aware → confirmed wall time (device-side run_id correlation)
  - boot_end elapsed_s when present
  - success / timeout

Requires: service account, device on boat power, BLE off, auto-log enabled.

  python3 ota_stress_harness.py --rounds 6
  python3 ota_stress_harness.py --rounds 6 --dry-run   # sheet poll only, no git ship
  python3 ota_stress_harness.py --watch                # monitor current upgrade only
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def _sheets():
    from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False), _sheet_id(creds)


def _read_local_version():
    text = (ROOT / "version.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return m.group(1).strip() if m else ""


def _bump_patch(ver: str) -> str:
    parts = ver.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def _parse_kv(detail: str) -> dict:
    out = {}
    for part in str(detail or "").split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _fetch_events(since_row_count=0):
    sheets, sid = _sheets()
    ev = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Events!A2:D").execute().get("values", [])
    return ev[since_row_count:]


def _fetch_power_tail():
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
                    "fw": row[idx.get("fw", 11)] if len(row) > idx.get("fw", 11) else "",
                }
            )
    return len(rows), out[-5:]


def _lifecycle_since(ev_rows):
    items = []
    for row in ev_rows:
        if len(row) < 4:
            continue
        if row[2] not in ("ota_lifecycle", "boot_ota"):
            continue
        kv = _parse_kv(row[3])
        kv["sheet_ts"] = row[0]
        kv["event"] = row[2]
        items.append(kv)
    return items


def _wait_for_target_fw(target_fw: str, baseline_pl_rows: int, timeout_s: int = 960):
    start = time.time()
    ev_base = _fetch_events()
    ev_skip = len(ev_base)
    run_report = {"target": target_fw, "phases": [], "success": False}

    while time.time() - start < timeout_s:
        count, tail = _fetch_power_tail()
        ev_new = _fetch_events(0)
        # full scan lifecycle each loop
        all_ev = _fetch_events()
        life = _lifecycle_since(all_ev)
        for item in life:
            if item.get("target_fw") == target_fw or item.get("phase") == "confirmed":
                if item not in run_report["phases"]:
                    run_report["phases"].append(item)

        if tail and tail[-1].get("fw") == target_fw and count > baseline_pl_rows:
            run_report["success"] = True
            run_report["confirmed_fw"] = tail[-1]["fw"]
            run_report["confirmed_ts"] = tail[-1]["ts"]
            run_report["elapsed_s"] = int(time.time() - start)
            return run_report

        if tail:
            print(
                "  … waiting fw=%s (last %s @ %s) +%ds"
                % (target_fw, tail[-1].get("fw"), tail[-1].get("ts"), int(time.time() - start))
            )
        time.sleep(30)

    run_report["timeout_s"] = timeout_s
    return run_report


def _ship_version(new_ver: str) -> bool:
    vpath = ROOT / "version.py"
    mpath = ROOT / "ota_manifest.json"
    vpath.write_text('VERSION = "%s"\n' % new_ver, encoding="utf-8")
    mtext = mpath.read_text(encoding="utf-8")
    mtext = re.sub(r'"version":\s*"[^"]+"', '"version": "%s"' % new_ver, mtext, count=1)
    mpath.write_text(mtext, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "validate_release.py")], cwd=str(ROOT))
    if r.returncode != 0:
        return False
    branch = "cursor/ota-stress-%s-5a55" % new_ver.replace(".", "")
    subprocess.run(["git", "checkout", "-B", branch], cwd=str(REPO), check=False)
    subprocess.run(["git", "add", "boat_monitor/version.py", "boat_monitor/ota_manifest.json"], cwd=str(REPO))
    subprocess.run(
        ["git", "commit", "-m", "release: OTA stress %s" % new_ver],
        cwd=str(REPO),
        check=False,
    )
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(REPO), check=False)
    subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            "release: OTA stress %s" % new_ver,
            "--body",
            "Automated OTA stress round target %s." % new_ver,
            "--base",
            "master",
            "--head",
            branch,
        ],
        cwd=str(REPO),
        check=False,
    )
    subprocess.run(["gh", "pr", "merge", branch, "--merge"], cwd=str(REPO), check=False)
    subprocess.run(["git", "checkout", "master"], cwd=str(REPO), check=False)
    subprocess.run(["git", "pull", "origin", "master"], cwd=str(REPO), check=False)
    r2 = subprocess.run(
        [sys.executable, str(ROOT / "validate_release.py"), "--check-github"],
        cwd=str(ROOT),
    )
    if r2.returncode != 0:
        return False
    r3 = subprocess.run([sys.executable, str(ROOT / "apply_ship_config.py")], cwd=str(ROOT))
    return r3.returncode == 0


def _set_min_fw_only(ver: str):
    from sheets_config_upsert import upsert_config_keys
    from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)
    upsert_config_keys(
        sheets,
        sid,
        [("min_fw_version", ver, "OTA stress harness target %s" % ver)],
    )
    print("CONFIG min_fw_version =", ver)


def run_rounds(n: int, dry_run: bool):
    start_ver = _read_local_version()
    print("Local master version:", start_ver)
    baseline_rows, _ = _fetch_power_tail()
    results = []
    ver = start_ver
    for i in range(n):
        ver = _bump_patch(ver)
        print("\n" + "=" * 70)
        print("ROUND %d/%d → target %s @ %s" % (i + 1, n, ver, datetime.now(timezone.utc).isoformat()))
        print("=" * 70)
        if not dry_run:
            if not _ship_version(ver):
                print("FAIL: ship", ver)
                results.append({"round": i + 1, "target": ver, "error": "ship_failed"})
                continue
        else:
            _set_min_fw_only(ver)
        pl_before, _ = _fetch_power_tail()
        rep = _wait_for_target_fw(ver, pl_before, timeout_s=960)
        rep["round"] = i + 1
        results.append(rep)
        print("ROUND RESULT:", json.dumps(rep, indent=2))
        if not rep.get("success"):
            print("Stopping stress pass after failed round.")
            break
    out = REPO / "ota_stress_results.json"
    out.write_text(json.dumps({"started": start_ver, "results": results}, indent=2), encoding="utf-8")
    print("\nWrote", out)
    return 0 if all(r.get("success") for r in results) else 1


def watch():
    print("Watching sheet (Ctrl+C to stop)...")
    while True:
        _, tail = _fetch_power_tail()
        ev = _fetch_events()
        life = _lifecycle_since(ev)[-8:]
        print("---", datetime.now(timezone.utc).strftime("%H:%M:%SZ"), "---")
        for row in tail:
            print(" PL", row)
        for item in life:
            print(" LC", item.get("sheet_ts"), item.get("phase"), item.get("run_id"), item.get("target_fw"), item.get("outcome", ""))
        time.sleep(45)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--dry-run", action="store_true", help="only bump min_fw on sheet, no git ship")
    p.add_argument("--watch", action="store_true")
    args = p.parse_args()
    if args.watch:
        watch()
        return 0
    return run_rounds(args.rounds, args.dry_run)


if __name__ == "__main__":
    sys.exit(main() or 0)
