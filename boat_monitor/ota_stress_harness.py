#!/usr/bin/env python3
"""
OTA stress harness — ship N sequential firmware versions and measure upgrade timing.

Metrics per round (from Google Sheet Events `ota_lifecycle` + Power_Log):
  - aware → confirmed wall time (device-side run_id correlation)
  - boot_end elapsed_s when present
  - success / timeout

Requires: service account, device on boat power, BLE off, auto-log enabled.
Device must be on firmware **≥ 1.1.61** (post-log OTA reboot). If stuck on 1.1.60
with `ota_action=1` and no log gap, use app **Reboot to Update** once, then re-run.

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


def _telemetry_since(ev_rows):
    """ota_lifecycle, boot_ota, ota_trace rows for timing analysis."""
    items = []
    for row in ev_rows:
        if len(row) < 4:
            continue
        if row[2] not in ("ota_lifecycle", "boot_ota", "ota_trace"):
            continue
        kv = _parse_kv(row[3])
        kv["sheet_ts"] = row[0]
        kv["event"] = row[2]
        kv["detail_raw"] = str(row[3])[:2000]
        if row[2] == "boot_ota" and "phase" not in kv:
            kv["phase"] = kv.get("outcome", "boot_ota")
        if row[2] == "ota_trace":
            kv["phase"] = "trace"
        items.append(kv)
    return items


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
        if row[2] == "boot_ota" and "phase" not in kv:
            kv["phase"] = kv.get("outcome", "boot_ota")
        items.append(kv)
    return items


def _phase_key(item):
    return (
        item.get("event"),
        item.get("phase"),
        item.get("run_id"),
        item.get("sheet_ts"),
        item.get("target_fw"),
    )


def _summarize_lifecycle(phases, target_fw):
    """Device-reported aware → confirmed timing for this target."""
    relevant = []
    for item in phases:
        tfw = item.get("target_fw") or ""
        ph = item.get("phase") or ""
        if tfw == target_fw or (ph == "confirmed" and item.get("fw_reported") == target_fw):
            relevant.append(item)
    by_phase = {}
    for item in relevant:
        ph = item.get("phase") or item.get("event") or "?"
        by_phase.setdefault(ph, []).append(item)
    confirmed = (by_phase.get("confirmed") or [None])[-1]
    aware = (by_phase.get("aware") or [None])[0]
    boot_end = (by_phase.get("boot_end") or [None])[-1]
    summary = {
        "lifecycle_rows": len(relevant),
        "phases_seen": sorted(by_phase.keys()),
    }
    if confirmed and confirmed.get("elapsed_total_s"):
        summary["device_aware_to_confirmed_s"] = int(confirmed["elapsed_total_s"])
    if boot_end and boot_end.get("elapsed_s"):
        summary["boot_ota_elapsed_s"] = int(boot_end["elapsed_s"])
    if aware:
        summary["aware_sheet_ts"] = aware.get("sheet_ts")
    if confirmed:
        summary["confirmed_sheet_ts"] = confirmed.get("sheet_ts")
    if aware and confirmed and aware.get("sheet_ts") and confirmed.get("sheet_ts"):
        summary["lifecycle_log"] = [
            {
                "sheet_ts": it.get("sheet_ts"),
                "phase": it.get("phase"),
                "run_id": it.get("run_id"),
                "detail_keys": {k: it[k] for k in it if k not in ("sheet_ts", "event")},
            }
            for it in sorted(relevant, key=lambda x: str(x.get("sheet_ts", "")))
        ]
    return summary


def _print_timing_block(phases, target_fw):
    """Human-readable timing from lifecycle + ota_trace for one upgrade."""
    life = [p for p in phases if p.get("event") in ("ota_lifecycle", "boot_ota")]
    traces = [p for p in phases if p.get("event") == "ota_trace"]
    print("\n--- TIMING target_fw=%s ---" % target_fw)
    for item in sorted(life, key=lambda x: str(x.get("sheet_ts", ""))):
        ph = item.get("phase") or item.get("event")
        bits = [item.get("sheet_ts"), ph]
        for k in (
            "run_id",
            "elapsed_s",
            "elapsed_total_s",
            "outcome",
            "http_sessions",
            "transport",
            "error",
            "fw",
            "fw_reported",
        ):
            if item.get(k):
                bits.append("%s=%s" % (k, item[k]))
        print("  LC", " | ".join(str(b) for b in bits if b))
    for tr in traces[-3:]:
        print("  TRACE @", tr.get("sheet_ts"))
        raw = tr.get("detail_raw") or ""
        for line in raw.split("\n")[:40]:
            print("    ", line[:200])
    print("--- end TIMING ---\n")


def _current_device_fw():
    _, tail = _fetch_power_tail()
    return tail[-1].get("fw") if tail else ""


def _wait_until_fw_at_least(min_fw: str, timeout_s: int = 3600, nudge_ota: bool = True):
    """Block until Power_Log reports fw >= min_fw (bootstrap before stress rounds)."""
    print("Bootstrap: waiting for device fw >= %s (timeout %ds)" % (min_fw, timeout_s))
    nudged = False
    start = time.time()
    while time.time() - start < timeout_s:
        fw = _current_device_fw()
        if fw and _parse_ver_tuple(fw) >= _parse_ver_tuple(min_fw):
            print("Bootstrap OK: device fw=%s" % fw)
            return True
        if nudge_ota and not nudged and fw:
            from sheets_config_upsert import upsert_config_keys

            sheets, sid = _sheets()
            upsert_config_keys(
                sheets,
                sid,
                [
                    ("min_fw_version", min_fw, "OTA stress bootstrap"),
                    ("boat-p2:cmd_ota", "1", "OTA stress bootstrap one-shot"),
                ],
            )
            print("Bootstrap: set min_fw=%s + cmd_ota=1 (device was fw=%s)" % (min_fw, fw))
            nudged = True
        print(
            "  … bootstrap fw=%s need>=%s +%ds" % (fw or "?", min_fw, int(time.time() - start)),
            flush=True,
        )
        time.sleep(45)
    print("Bootstrap TIMEOUT — device never reached %s" % min_fw)
    return False


def _parse_ver_tuple(text):
    parts = []
    for p in str(text or "").split("."):
        try:
            parts.append(int(p))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _write_results(path, start_ver, n, results, final=False):
    ok = [r for r in results if r.get("success")]
    payload = {
        "started": start_ver,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "rounds_requested": n,
        "complete": final,
        "results": results,
        "summary": {
            "success_count": len(ok),
            "fail_count": len(results) - len(ok),
            "wall_times_s": [r.get("wall_elapsed_s") for r in ok],
            "device_aware_to_confirmed_s": [
                r.get("device_aware_to_confirmed_s") for r in ok if r.get("device_aware_to_confirmed_s")
            ],
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _wait_for_target_fw(target_fw: str, baseline_pl_rows: int, timeout_s: int = 2400):
    start = time.time()
    run_report = {"target": target_fw, "phases": [], "phase_keys": set(), "success": False}

    while time.time() - start < timeout_s:
        count, tail = _fetch_power_tail()
        all_ev = _fetch_events()
        telem = _telemetry_since(all_ev)
        for item in telem:
            tfw = item.get("target_fw") or ""
            ph = item.get("phase") or ""
            match = (
                tfw == target_fw
                or (ph == "confirmed" and item.get("fw_reported") == target_fw)
                or item.get("event") == "ota_trace"
                or (item.get("event") == "boot_ota" and tfw in ("", target_fw))
            )
            if not match and item.get("event") == "ota_lifecycle":
                if item.get("fw") and _parse_ver_tuple(item.get("fw")) <= _parse_ver_tuple(target_fw):
                    match = True
            if match:
                pk = _phase_key(item) if item.get("event") != "ota_trace" else ("ota_trace", item.get("sheet_ts"))
                if pk not in run_report["phase_keys"]:
                    run_report["phase_keys"].add(pk)
                    run_report["phases"].append(item)
        life = [p for p in run_report["phases"] if p.get("event") in ("ota_lifecycle", "boot_ota")]

        confirmed_row = None
        if tail and tail[-1].get("fw") == target_fw:
            confirmed_row = tail[-1]
        else:
            for row in reversed(tail or []):
                if row.get("fw") == target_fw:
                    confirmed_row = row
                    break
        # Prefer a new Power_Log row after ship; accept latest fw match if sheet already shows target.
        if confirmed_row and (count > baseline_pl_rows or (tail and tail[-1].get("fw") == target_fw)):
            run_report["success"] = True
            run_report["confirmed_fw"] = confirmed_row["fw"]
            run_report["confirmed_ts"] = confirmed_row["ts"]
            run_report["wall_elapsed_s"] = int(time.time() - start)
            run_report["elapsed_s"] = run_report["wall_elapsed_s"]
            run_report.update(_summarize_lifecycle(life, target_fw))
            run_report["ota_trace_count"] = sum(1 for p in run_report["phases"] if p.get("event") == "ota_trace")
            del run_report["phase_keys"]
            _print_timing_block(run_report["phases"], target_fw)
            return run_report

        if tail:
            print(
                "  … waiting fw=%s (last %s @ %s) +%ds"
                % (target_fw, tail[-1].get("fw"), tail[-1].get("ts"), int(time.time() - start))
            )
        time.sleep(30)

    run_report["timeout_s"] = timeout_s
    life = [p for p in run_report.get("phases", []) if p.get("event") in ("ota_lifecycle", "boot_ota")]
    run_report.update(_summarize_lifecycle(life, target_fw))
    if "phase_keys" in run_report:
        del run_report["phase_keys"]
    _print_timing_block(run_report.get("phases", []), target_fw)
    return run_report


def _ship_version(new_ver: str) -> bool:
    vpath = ROOT / "version.py"
    mpath = ROOT / "ota_manifest.json"
    vpath.write_text('VERSION = "%s"\n' % new_ver, encoding="utf-8")
    mtext = mpath.read_text(encoding="utf-8")
    mtext = re.sub(r'"version":\s*"[^"]+"', '"version": "%s"' % new_ver, mtext, count=1)
    mpath.write_text(mtext, encoding="utf-8")
    fp = subprocess.run(
        [sys.executable, str(ROOT / "apply_recovery_manifest.py"), "--ram-fix"],
        cwd=str(ROOT),
        check=False,
    )
    if fp.returncode != 0:
        print("WARN: ram-fix manifest step failed")
    # RAM-safe stress: per-file cellular OTA only (no .bmota — boot OTA OOM on ~190KB bundle).
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
    subprocess.run(["git", "checkout", "master"], cwd=str(REPO), check=False)
    subprocess.run(["git", "pull", "origin", "master"], cwd=str(REPO), check=False)
    subprocess.run(
        ["git", "merge", branch, "-m", "release: OTA stress %s" % new_ver],
        cwd=str(REPO),
        check=False,
    )
    subprocess.run(["git", "push", "origin", "master"], cwd=str(REPO), check=False)
    subprocess.run(["git", "checkout", "master"], cwd=str(REPO), check=False)
    # raw.githubusercontent.com can lag GitHub master by a few minutes
    for attempt in range(12):
        r2 = subprocess.run(
            [sys.executable, str(ROOT / "validate_release.py"), "--check-github"],
            cwd=str(ROOT),
        )
        if r2.returncode == 0:
            break
        time.sleep(15)
    else:
        print("WARN: GitHub raw manifest still stale; applying sheet min_fw anyway")
    r3 = subprocess.run([sys.executable, str(ROOT / "apply_ship_config.py")], cwd=str(ROOT))
    if r3.returncode != 0:
        from sheets_config_upsert import upsert_config_keys

        sheets, sid = _sheets()
        upsert_config_keys(
            sheets,
            sid,
            [("min_fw_version", new_ver, "OTA stress harness target %s (CDN fallback)" % new_ver)],
        )
        print("CONFIG min_fw_version =", new_ver, "(fallback)")
        return True
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


def run_rounds(n: int, dry_run: bool, bootstrap: bool, bootstrap_timeout_s: int):
    start_ver = _read_local_version()
    print("Local master version:", start_ver)
    if bootstrap and not dry_run:
        if not _wait_until_fw_at_least(start_ver, timeout_s=bootstrap_timeout_s):
            return 1
    elif bootstrap:
        fw = _current_device_fw()
        print("Dry-run bootstrap skip (device fw=%s, need>=%s)" % (fw, start_ver))
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
        rep = _wait_for_target_fw(ver, pl_before, timeout_s=2400)
        rep["round"] = i + 1
        results.append(rep)
        print("ROUND RESULT:", json.dumps(rep, indent=2))
        _write_results(REPO / "ota_stress_results.json", start_ver, n, results, final=False)
        try:
            subprocess.run(
                [sys.executable, str(ROOT / "ota_stress_analyze.py"), "--since", "Aug 9, 2026 4:00 PM"],
                cwd=str(ROOT),
                timeout=120,
            )
        except Exception:
            pass
        if not rep.get("success"):
            print("Stopping stress pass after failed round.")
            break
    payload = _write_results(REPO / "ota_stress_results.json", start_ver, n, results, final=True)
    print("\nWrote", REPO / "ota_stress_results.json")
    print("SUMMARY:", json.dumps(payload["summary"], indent=2))
    return 0 if results and all(r.get("success") for r in results) else 1


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
    p.add_argument("--no-bootstrap", action="store_true", help="skip wait for device fw >= repo VERSION")
    p.add_argument("--bootstrap-timeout", type=int, default=7200, help="seconds to wait for bootstrap (default 2h)")
    p.add_argument("--watch", action="store_true")
    args = p.parse_args()
    if args.watch:
        watch()
        return 0
    return run_rounds(
        args.rounds,
        args.dry_run,
        bootstrap=not args.no_bootstrap,
        bootstrap_timeout_s=args.bootstrap_timeout,
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
