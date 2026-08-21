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
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OTA_STRESS_BRANCH_SUFFIX = os.environ.get("OTA_STRESS_BRANCH_SUFFIX", "abe2").strip() or "abe2"


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
                    "uplink": (
                        row[idx.get("uplink", 12)]
                        if len(row) > idx.get("uplink", 12)
                        else ""
                    ),
                    "mode": row[idx.get("mode", 2)] if len(row) > idx.get("mode", 2) else "",
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


def _boot_ota_success_for_target(phases, target_fw: str):
    """boot_ota row with outcome=success and fw_target matching ship target."""
    for item in reversed(phases or []):
        if item.get("event") != "boot_ota":
            continue
        outcome = str(item.get("outcome") or item.get("phase") or "")
        if outcome != "success":
            continue
        tft = str(item.get("fw_target") or item.get("target_fw") or "")
        if tft == target_fw:
            return item
    return None


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
            from ota_stress_rules import preflight_sheet_or_exit
            from sheets_config_upsert import upsert_config_keys

            sheets, sid = _sheets()
            preflight_sheet_or_exit(sheets, sid)
            upsert_config_keys(
                sheets,
                sid,
                [("min_fw_version", min_fw, "OTA stress bootstrap")],
            )
            print("Bootstrap: sheet preflight + min_fw=%s (device was fw=%s)" % (min_fw, fw))
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


def _ensure_watch_running():
    """Start boat_p2_watch in background if state file is missing or stale."""
    from ota_stress_rules import WATCH_STATE_MAX_AGE_S

    state = REPO / "boat_p2_watch_state.json"
    import time

    stale = True
    if state.is_file():
        stale = (time.time() - state.stat().st_mtime) > WATCH_STATE_MAX_AGE_S
    if not stale:
        print("boat_p2_watch already running")
        return
    print("Starting boat_p2_watch (background)...")
    subprocess.Popen(
        [sys.executable, str(ROOT / "boat_p2_watch.py"), "--interval", "60"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(3)
        if state.is_file() and (time.time() - state.stat().st_mtime) <= WATCH_STATE_MAX_AGE_S:
            print("boat_p2_watch OK")
            return
    print("WARN: boat_p2_watch may not have started — preflight will fail", file=sys.stderr)


def _pause_stress_on_failure(reason: str):
    """Set min_fw to device fw so reboot storms stop after a failed round."""
    from ota_stress_rules import pause_min_fw_to_device

    fw = _current_device_fw()
    if not fw:
        print("WARN: cannot pause stress — no device fw on sheet", file=sys.stderr)
        return
    sheets, sid = _sheets()
    pause_min_fw_to_device(sheets, sid, fw, reason)


def _uplink_matches(actual, expected):
    actual = str(actual or "").strip().lower()
    if not expected:
        return True
    if expected == "wifi":
        return bool(actual) and actual != "cellular"
    return actual == expected


def _wait_for_target_fw(
    target_fw: str,
    baseline_pl_rows: int,
    timeout_s: int = 2400,
    expected_uplink: str | None = None,
    baseline_event_rows: int = 0,
    boot_start_timeout_s: int | None = None,
):
    from ota_stress_rules import (
        BOOT_START_TIMEOUT_S,
        POST_OTA_POWER_LOG_GRACE_S,
        detect_reboot_trap,
        pause_min_fw_to_device,
    )

    start = time.time()
    run_report = {"target": target_fw, "phases": [], "phase_keys": set(), "success": False}
    saw_boot_start = False
    boot_start_limit = int(boot_start_timeout_s or BOOT_START_TIMEOUT_S)
    boot_start_deadline = start + boot_start_limit
    ota_success_at = None

    while time.time() - start < timeout_s:
        count, tail = _fetch_power_tail()
        round_events = _fetch_events(since_row_count=baseline_event_rows)
        telem = _telemetry_since(round_events)
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
                    if ph == "boot_start":
                        saw_boot_start = True
        life = [p for p in run_report["phases"] if p.get("event") in ("ota_lifecycle", "boot_ota")]
        fatal = None
        for item in reversed(run_report["phases"]):
            detail = " ".join(
                str(item.get(key) or "")
                for key in ("error", "outcome", "detail_raw")
            ).lower()
            if "low_flash" in detail or "no space left" in detail:
                fatal = "fatal OTA storage preflight: %s" % detail[:240]
                break
        if fatal:
            cur_fw = tail[-1].get("fw") if tail else "?"
            if cur_fw and cur_fw != "?":
                sheets, sid = _sheets()
                pause_min_fw_to_device(sheets, sid, cur_fw, fatal)
            run_report["error"] = fatal
            print("FAIL:", fatal)
            break
        ota_ok = _boot_ota_success_for_target(life, target_fw)
        if ota_ok and ota_success_at is None:
            ota_success_at = time.time()
            print(
                "  … boot_ota success for %s (waiting Power_Log confirm, grace %ds)"
                % (target_fw, POST_OTA_POWER_LOG_GRACE_S)
            )

        confirmed_row = None
        if tail and tail[-1].get("fw") == target_fw:
            confirmed_row = tail[-1]
        else:
            for row in reversed(tail or []):
                if row.get("fw") == target_fw:
                    confirmed_row = row
                    break
        transport_confirmed = confirmed_row and _uplink_matches(
            confirmed_row.get("uplink"),
            expected_uplink,
        )
        pl_confirmed = confirmed_row and transport_confirmed and (
            count > baseline_pl_rows
            or (tail and tail[-1].get("fw") == target_fw)
            or ota_ok
        )
        ota_grace_expired = (
            ota_success_at is not None
            and (time.time() - ota_success_at) >= POST_OTA_POWER_LOG_GRACE_S
        )
        if pl_confirmed or (ota_grace_expired and not expected_uplink):
            run_report["success"] = True
            run_report["confirmed_fw"] = (
                confirmed_row["fw"] if confirmed_row else target_fw
            )
            run_report["confirmed_ts"] = (
                confirmed_row["ts"] if confirmed_row else "boot_ota_only"
            )
            if confirmed_row:
                run_report["confirmed_uplink"] = confirmed_row.get("uplink")
                run_report["confirmed_mode"] = confirmed_row.get("mode")
            if ota_ok and not confirmed_row:
                run_report["confirmed_via"] = "boot_ota"
            run_report["wall_elapsed_s"] = int(time.time() - start)
            run_report["elapsed_s"] = run_report["wall_elapsed_s"]
            run_report.update(_summarize_lifecycle(life, target_fw))
            run_report["ota_trace_count"] = sum(1 for p in run_report["phases"] if p.get("event") == "ota_trace")
            del run_report["phase_keys"]
            _print_timing_block(run_report["phases"], target_fw)
            return run_report

        if tail:
            cur_fw = tail[-1].get("fw") or "?"
            trap = detect_reboot_trap(round_events, cur_fw, target_fw)
            if trap:
                sheets, sid = _sheets()
                pause_min_fw_to_device(sheets, sid, cur_fw, trap)
                run_report["error"] = trap
                print("FAIL:", trap)
                break
            ota_note = ""
            if ota_success_at:
                ota_note = " ota_ok+%ds" % int(time.time() - ota_success_at)
            if confirmed_row and not transport_confirmed:
                ota_note += " target_fw_seen_uplink=%s need=%s" % (
                    confirmed_row.get("uplink") or "?",
                    expected_uplink,
                )
            print(
                "  … waiting fw=%s (last %s @ %s) +%ds boot_start=%s%s"
                % (
                    target_fw,
                    cur_fw,
                    tail[-1].get("ts"),
                    int(time.time() - start),
                    saw_boot_start,
                    ota_note,
                )
            )
            if (
                not saw_boot_start
                and time.time() > boot_start_deadline
                and _parse_ver_tuple(cur_fw) < _parse_ver_tuple(target_fw)
            ):
                err = (
                    "no_boot_start in %ds — flash backoff trap? USB patch-only --enable-boot-ota"
                    % boot_start_limit
                )
                run_report["error"] = err
                print("FAIL:", err)
                sheets, sid = _sheets()
                pause_min_fw_to_device(sheets, sid, cur_fw, err)
                break
        time.sleep(30)

    run_report["timeout_s"] = timeout_s
    life = [p for p in run_report.get("phases", []) if p.get("event") in ("ota_lifecycle", "boot_ota")]
    run_report.update(_summarize_lifecycle(life, target_fw))
    if "phase_keys" in run_report:
        del run_report["phase_keys"]
    _print_timing_block(run_report.get("phases", []), target_fw)
    return run_report


def _run_checked(command, description):
    try:
        subprocess.run(command, cwd=str(REPO), check=True)
        return True
    except subprocess.CalledProcessError as exc:
        print("FAIL: %s (exit %s): %s" % (description, exc.returncode, " ".join(command)))
        return False


def _release_worktree_ready():
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(REPO),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if branch != "master":
        print("FAIL: OTA ship must start on master, current branch is %s" % (branch or "?"))
        return False
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=str(REPO),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        print("FAIL: tracked worktree changes present before OTA ship:\n%s" % status)
        return False
    return True


def _normalize_master_manifest_for_stress(version, allow_master_push):
    """Commit a version-only manifest at the installed baseline before round 1."""
    if not allow_master_push:
        print("FAIL: normalizing the master manifest requires --allow-master-push")
        return False
    if not _release_worktree_ready():
        return False
    manifest = subprocess.run(
        [
            sys.executable,
            str(ROOT / "apply_recovery_manifest.py"),
            "--version-only",
        ],
        cwd=str(ROOT),
    )
    if manifest.returncode != 0:
        return False
    validate = subprocess.run(
        [
            sys.executable,
            str(ROOT / "validate_release.py"),
            "--max-files",
            "1",
            "--enforce-master-policy",
        ],
        cwd=str(ROOT),
    )
    if validate.returncode != 0:
        return False
    changed = subprocess.run(
        ["git", "diff", "--quiet", "--", "boat_monitor/ota_manifest.json"],
        cwd=str(REPO),
    ).returncode
    if changed == 0:
        return True

    branch = "cursor/ota-stress-baseline-%s-%s" % (
        version.replace(".", ""),
        OTA_STRESS_BRANCH_SUFFIX,
    )
    commands = (
        (["git", "checkout", "-b", branch], "create baseline manifest branch"),
        (["git", "add", "boat_monitor/ota_manifest.json"], "stage baseline manifest"),
        (
            ["git", "commit", "-m", "release: prepare OTA stress baseline %s" % version],
            "commit baseline manifest",
        ),
        (["git", "push", "-u", "origin", branch], "push baseline manifest branch"),
        (["git", "checkout", "master"], "return to master"),
        (["git", "pull", "origin", "master"], "update master"),
        (
            ["git", "merge", branch, "-m", "release: prepare OTA stress baseline %s" % version],
            "merge baseline manifest",
        ),
        (["git", "push", "-u", "origin", "master"], "push baseline master"),
    )
    for command, description in commands:
        if not _run_checked(command, description):
            return False
    for _ in range(12):
        remote = subprocess.run(
            [sys.executable, str(ROOT / "validate_release.py"), "--check-github"],
            cwd=str(ROOT),
        )
        if remote.returncode == 0:
            return True
        time.sleep(15)
    print("FAIL: GitHub raw baseline manifest did not converge")
    return False


def _ship_version(
    new_ver: str,
    manifest_mode: str = "version-only",
    profile: str = "underway",
    allow_master_push: bool = False,
) -> bool:
    if not allow_master_push:
        print("FAIL: live shipping requires --allow-master-push")
        return False
    if not _release_worktree_ready():
        return False
    vpath = ROOT / "version.py"
    mpath = ROOT / "ota_manifest.json"
    vpath.write_text('VERSION = "%s"\n' % new_ver, encoding="utf-8")
    mtext = mpath.read_text(encoding="utf-8")
    mtext = re.sub(r'"version":\s*"[^"]+"', '"version": "%s"' % new_ver, mtext, count=1)
    mpath.write_text(mtext, encoding="utf-8")
    if manifest_mode == "bootstrap-rules":
        manifest_arg = "--bootstrap-rules"
        max_files = "2"
        manifest_check = None
    else:
        from ota_stress_rules import assert_version_only_manifest

        manifest_arg = "--version-only"
        max_files = "1"
        manifest_check = assert_version_only_manifest
    fp = subprocess.run(
        [sys.executable, str(ROOT / "apply_recovery_manifest.py"), manifest_arg],
        cwd=str(ROOT),
    )
    if fp.returncode != 0:
        print("FAIL: manifest step failed (%s)" % manifest_arg)
        return False
    if manifest_check:
        try:
            manifest_check()
        except SystemExit as exc:
            print("FAIL:", exc)
            return False
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "validate_release.py"),
            "--max-files",
            max_files,
            "--enforce-master-policy",
        ],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        return False
    branch = "cursor/ota-stress-%s-%s" % (new_ver.replace(".", ""), OTA_STRESS_BRANCH_SUFFIX)
    commands = (
        (["git", "checkout", "-b", branch], "create release branch"),
        (
            ["git", "add", "boat_monitor/version.py", "boat_monitor/ota_manifest.json"],
            "stage release files",
        ),
        (
            ["git", "commit", "-m", "release: OTA stress %s" % new_ver],
            "commit release",
        ),
        (["git", "push", "-u", "origin", branch], "push release branch"),
        (["git", "checkout", "master"], "return to master"),
        (["git", "pull", "origin", "master"], "update master"),
        (
            ["git", "merge", branch, "-m", "release: OTA stress %s" % new_ver],
            "merge release",
        ),
        (["git", "push", "-u", "origin", "master"], "push master"),
    )
    for command, description in commands:
        if not _run_checked(command, description):
            return False
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
        print("FAIL: GitHub raw manifest still stale; sheet target was not changed")
        return False
    r3 = subprocess.run(
        [
            sys.executable,
            str(ROOT / "apply_ship_config.py"),
            "--profile",
            profile,
        ],
        cwd=str(ROOT),
    )
    if r3.returncode != 0:
        print("FAIL: release shipped but sheet configuration was not changed")
        return False
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


ROUND_COOLDOWN_S = 90


def _bootstrap_rules_if_needed(
    dry_run: bool,
    profile: str,
    allow_master_push: bool,
) -> bool:
    """Ship remote_boot_config.py once so version-only rounds can self-heal backoff."""
    dev_fw = _current_device_fw()
    if not dev_fw:
        print("Bootstrap-rules skip: no device fw on sheet")
        return True
    target = _bump_patch(dev_fw)
    print(
        "Bootstrap-rules: ship %s with version.py + remote_boot_config.py (device was %s)"
        % (target, dev_fw)
    )
    if dry_run:
        return True
    pl_before, _ = _fetch_power_tail()
    event_before = len(_fetch_events())
    if not _ship_version(
        target,
        manifest_mode="bootstrap-rules",
        profile=profile,
        allow_master_push=allow_master_push,
    ):
        print("FAIL: bootstrap-rules ship", target)
        return False
    rep = _wait_for_target_fw(
        target,
        pl_before,
        timeout_s=2400,
        baseline_event_rows=event_before,
    )
    print("BOOTSTRAP-RULES RESULT:", json.dumps(rep, indent=2))
    if not rep.get("success"):
        print("FAIL: bootstrap-rules did not confirm; version-only rounds were not started")
        return False
    time.sleep(ROUND_COOLDOWN_S)
    return True


def run_rounds(
    n: int,
    dry_run: bool,
    bootstrap: bool,
    bootstrap_timeout_s: int,
    profile: str = "underway",
    round_timeout_s: int = 2400,
    reset_v50: bool = False,
    allow_master_push: bool = False,
):
    start_ver = _read_local_version()
    print("Local master version:", start_ver, "profile:", profile)
    if not dry_run:
        from ota_stress_rules import (
            assert_version_only_manifest,
            device_ahead_of_repo,
            preflight_stress_campaign,
            reset_v50_full,
        )

        _ensure_watch_running()
        try:
            assert_version_only_manifest()
        except SystemExit as exc:
            print("Baseline manifest requires normalization:", exc)
            if not _normalize_master_manifest_for_stress(
                start_ver,
                allow_master_push=allow_master_push,
            ):
                return 1
            assert_version_only_manifest()
        sheets, sid = _sheets()
        if reset_v50:
            reset_v50_full(sheets, sid)
        dev_fw = _current_device_fw()
        all_ev = _fetch_events()
        try:
            preflight_stress_campaign(
                sheets,
                sid,
                profile=profile,
                device_fw=dev_fw or "",
                repo_ver=start_ver,
                require_watch=True,
                events=all_ev,
            )
        except SystemExit as exc:
            print("FAIL:", exc)
            return 1
        print("OK: sheet preflight (recovery keys + cleared one-shots)")
        upsert_clear_pending = [
            ("cmd_clear_pending_ota", "1", "ota_stress: clear stale pending_ota"),
            ("clear_pending_ota", "1", "ota_stress: clear stale pending_ota"),
        ]
        from sheets_config_upsert import upsert_config_keys

        upsert_config_keys(sheets, sid, upsert_clear_pending)
        dev_fw = _current_device_fw()
        if device_ahead_of_repo(dev_fw, start_ver):
            print("WARN: device fw %s ahead of repo %s" % (dev_fw, start_ver))
        # USB ram-fix already ships remote_boot_config.py; skip cellular bootstrap OTA.
        if dev_fw and _parse_ver_tuple(dev_fw) >= _parse_ver_tuple(start_ver):
            print(
                "Bootstrap-rules skip: device fw %s >= repo %s (USB ram-fix assumed)"
                % (dev_fw, start_ver)
            )
        elif not _bootstrap_rules_if_needed(
            dry_run,
            profile=profile,
            allow_master_push=allow_master_push,
        ):
            return 1
    if bootstrap and not dry_run:
        if not _wait_until_fw_at_least(start_ver, timeout_s=bootstrap_timeout_s):
            return 1
    elif bootstrap:
        fw = _current_device_fw()
        print("Dry-run bootstrap skip (device fw=%s, need>=%s)" % (fw, start_ver))
    results = []
    ver = start_ver
    for i in range(n):
        ver = _bump_patch(ver)
        print("\n" + "=" * 70)
        print("ROUND %d/%d → target %s @ %s" % (i + 1, n, ver, datetime.now(timezone.utc).isoformat()))
        print("=" * 70)
        if not dry_run:
            sheets, sid = _sheets()
            from ota_stress_rules import preflight_sheet, detect_reboot_trap, pause_min_fw_to_device

            dev_fw = _current_device_fw() or ""
            all_ev = _fetch_events()
            trap = detect_reboot_trap(all_ev, dev_fw, ver)
            if trap:
                pause_min_fw_to_device(sheets, sid, dev_fw, trap)
                print("FAIL:", trap)
                results.append({"round": i + 1, "target": ver, "error": trap})
                break
            preflight_sheet(sheets, sid, profile=profile)
            pl_before, _ = _fetch_power_tail()
            event_before = len(_fetch_events())
            if not _ship_version(
                ver,
                profile=profile,
                allow_master_push=allow_master_push,
            ):
                print("FAIL: ship", ver)
                results.append({"round": i + 1, "target": ver, "error": "ship_failed"})
                _pause_stress_on_failure("ship failed for %s" % ver)
                break
        else:
            pl_before, _ = _fetch_power_tail()
            _set_min_fw_only(ver)
        expected_uplink = "wifi" if profile == "dock" else None
        if profile == "dock":
            from ota_stress_rules import DOCK_BOOT_START_TIMEOUT_S

            boot_start_timeout_s = DOCK_BOOT_START_TIMEOUT_S
        else:
            boot_start_timeout_s = None
        rep = _wait_for_target_fw(
            ver,
            pl_before,
            timeout_s=round_timeout_s,
            expected_uplink=expected_uplink,
            baseline_event_rows=event_before if not dry_run else 0,
            boot_start_timeout_s=boot_start_timeout_s,
        )
        rep["round"] = i + 1
        rep["profile"] = profile
        rep["expected_uplink"] = expected_uplink
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
            if not dry_run:
                _pause_stress_on_failure(rep.get("error") or "round failed")
            break
        if not dry_run and rep.get("success"):
            print("Round cooldown %ds before next ship..." % ROUND_COOLDOWN_S)
            time.sleep(ROUND_COOLDOWN_S)
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
    p.add_argument(
        "--profile",
        choices=("underway", "dock"),
        default="underway",
        help="underway=cellular key-on stress; dock=standby Wi-Fi-first",
    )
    p.add_argument(
        "--round-timeout",
        type=int,
        default=None,
        help="seconds to wait per round (default 2400 underway, 3600 dock)",
    )
    p.add_argument(
        "--reset-v50",
        action="store_true",
        help="set boat-p2:v50_full_at_utc now (bank 100%% baseline)",
    )
    p.add_argument(
        "--allow-master-push",
        action="store_true",
        help="explicitly authorize release branches, merges, and pushes to master",
    )
    p.add_argument("--watch", action="store_true")
    args = p.parse_args()
    if args.watch:
        watch()
        return 0
    if not args.dry_run and not args.allow_master_push:
        p.error("live campaigns require --allow-master-push")
    from ota_stress_rules import DOCK_ROUND_TIMEOUT_S

    round_timeout = args.round_timeout
    if round_timeout is None:
        round_timeout = DOCK_ROUND_TIMEOUT_S if args.profile == "dock" else 2400
    return run_rounds(
        args.rounds,
        args.dry_run,
        bootstrap=not args.no_bootstrap,
        bootstrap_timeout_s=args.bootstrap_timeout,
        profile=args.profile,
        round_timeout_s=round_timeout,
        reset_v50=args.reset_v50,
        allow_master_push=args.allow_master_push,
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
