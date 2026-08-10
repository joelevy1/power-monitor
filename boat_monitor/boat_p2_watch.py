#!/usr/bin/env python3
"""
Poll boat-p2 on the Google Sheet every N seconds; log status and take safe actions.

  python3 boat_p2_watch.py
  python3 boat_p2_watch.py --interval 60 --once

Actions (automatic):
  - cmd_clear_pending_ota=1 one-shot if fw >= min_fw but reboot storm detected
  - Append human-readable lines to ../boat_p2_watch.log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
LOG_PATH = REPO / "boat_p2_watch.log"
STATE_PATH = REPO / "boat_p2_watch_state.json"
DEVICE = "boat-p2"
# Power on + min_fw set but Power_Log fw unchanged → escalate (cellular OTA stuck).
GIVE_UP_STUCK_MINUTES = 45
BOOT_OTA_MAX_S = 420


def _log(msg):
    line = "%s %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), msg)
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _sheets():
    from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False), _sheet_id(creds)


def _parse_version(text):
    parts = []
    for p in str(text or "").split("."):
        try:
            parts.append(int(p))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _version_lt(a, b):
    return _parse_version(a) < _parse_version(b)


def _parse_sheet_ts(text):
    try:
        return datetime.strptime(str(text).strip(), "%b %d, %Y %I:%M %p")
    except Exception:
        return None


def _config_map(sheets, sid):
    rows = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Config!A2:C").execute().get("values", [])
    out = {}
    for row in rows:
        if row and row[0]:
            out[str(row[0]).strip()] = str(row[1]).strip() if len(row) > 1 else ""
    return out


def _power_tail(sheets, sid, n=8):
    hdr = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Power_Log!1:1").execute().get("values", [[]])[0]
    idx = {h: i for i, h in enumerate(hdr)}
    rows = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Power_Log!A2:N").execute().get("values", [])
    p2 = [r for r in rows if len(r) > 1 and r[1] == DEVICE]
    tail = p2[-n:]

    def g(r, k):
        i = idx.get(k)
        return r[i] if i is not None and i < len(r) else ""

    return tail, g


def _events_tail(sheets, sid, n=40):
    ev = sheets.spreadsheets().values().get(spreadsheetId=sid, range="Events!A2:D").execute().get("values", [])
    p2 = [r for r in ev if len(r) > 1 and r[1] == DEVICE]
    return p2[-n:]


def _maybe_clear_pending_ota(cfg, events, last_fw, force=False):
    if cfg.get("cmd_clear_pending_ota") == "1":
        return False
    if not force:
        min_fw = cfg.get("min_fw_version") or ""
        if not min_fw or not last_fw or last_fw == "?":
            return False
        if _version_lt(last_fw, min_fw):
            return False
    recent = events[-15:]
    rq = sum(
        1
        for r in recent
        if len(r) > 2 and r[2] == "ota_lifecycle" and "reboot_queued" in str(r[3])
    )
    if not force and rq < 4:
        return False
    if cfg.get("cmd_clear_pending_ota") == "1":
        return False
    from sheets_config_upsert import upsert_config_keys

    sheets, sid = _sheets()
    upsert_config_keys(
        sheets,
        sid,
        [("cmd_clear_pending_ota", "1", "boat_p2_watch: reboot storm at min_fw")],
    )
    min_fw_cfg = cfg.get("min_fw_version") or "?"
    _log(
        "ACTION set cmd_clear_pending_ota=1 (fw %s min %s reboot_queued x%s force=%s)"
        % (last_fw, min_fw_cfg, rq, force)
    )
    return True


def poll_once():
    sheets, sid = _sheets()
    cfg = _config_map(sheets, sid)
    min_fw = cfg.get("min_fw_version", "?")
    tail, g = _power_tail(sheets, sid)
    events = _events_tail(sheets, sid)

    last_pl = tail[-1] if tail else None
    last_fw = g(last_pl, "fw") if last_pl else "?"
    last_ts = g(last_pl, "timestamp_utc") if last_pl else "none"
    last_mode = g(last_pl, "mode") if last_pl else "?"

    try:
        prev = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.is_file() else {}
    except Exception:
        prev = {}
    prev_ts = prev.get("power_log_ts")
    if last_ts and last_ts != "none" and prev_ts and prev_ts != last_ts:
        dt_new = _parse_sheet_ts(last_ts)
        dt_old = _parse_sheet_ts(prev_ts)
        if dt_new and dt_old:
            delta_s = int((dt_new - dt_old).total_seconds())
            _log(
                "POWER_LOG_CADENCE new_row delta_s=%s mode=%s fw=%s (was ts=%s)"
                % (delta_s, last_mode, last_fw, prev_ts)
            )

    ev_names = Counter(r[2] for r in events[-12:] if len(r) > 2)
    last_ev = events[-1] if events else None
    last_ev_line = ""
    if last_ev:
        last_ev_line = "%s %s %s" % (last_ev[0], last_ev[2], str(last_ev[3])[:100])

    lifecycle_fw = None
    for r in reversed(events):
        if len(r) > 3 and r[2] == "ota_lifecycle" and "fw=" in str(r[3]):
            m = re.search(r"fw=([0-9.]+)", str(r[3]))
            if m:
                lifecycle_fw = m.group(1)
                break

    recent = events[-20:]
    rq = sum(
        1
        for r in recent
        if len(r) > 2 and r[2] == "ota_lifecycle" and "reboot_queued" in str(r[3])
    )

    status = "unknown"
    detail = []
    if rq >= 4:
        status = "reboot_loop"
        detail.append("reboot_queued x%s (recovery OTA / clear_pending)" % rq)
        _maybe_clear_pending_ota(cfg, events, lifecycle_fw or last_fw, force=True)
    elif last_fw != "?" and min_fw != "?" and _version_lt(last_fw, min_fw):
        status = "ota_pending"
        detail.append("Power_Log fw %s < min %s" % (last_fw, min_fw))
    elif lifecycle_fw and min_fw != "?" and not _version_lt(lifecycle_fw, min_fw):
        if last_fw != "?" and last_fw != lifecycle_fw and not _version_lt(lifecycle_fw, last_fw):
            status = "sheet_stale_fw"
            detail.append("Device reports %s in Events; Power_Log still %s" % (lifecycle_fw, last_fw))
        else:
            status = "healthy"
            detail.append("At or above min_fw (lifecycle %s, log %s)" % (lifecycle_fw, last_fw))
    else:
        status = "watch"
        detail.append("lifecycle_fw=%s log_fw=%s" % (lifecycle_fw, last_fw))

    now = datetime.now(timezone.utc)
    stuck_since = prev.get("ota_stuck_since_utc")
    give_up_logged = prev.get("give_up_logged", False)
    has_file_done = any(
        len(r) > 3 and r[2] == "ota_lifecycle" and "phase=file_done" in str(r[3]) for r in events[-50:]
    )
    has_new_telemetry = any(
        len(r) > 3 and r[2] in ("device_stats", "ota_trace") for r in events[-30:]
    )
    ota_behind = (
        last_fw != "?"
        and min_fw != "?"
        and _version_lt(last_fw, min_fw)
    )
    if ota_behind:
        if not stuck_since:
            stuck_since = now.isoformat()
        else:
            try:
                t0 = datetime.fromisoformat(stuck_since.replace("Z", "+00:00"))
                stuck_min = int((now - t0).total_seconds() / 60)
            except Exception:
                stuck_min = 0
            if stuck_min >= GIVE_UP_STUCK_MINUTES and not give_up_logged:
                _log(
                    "ESCALATE give_up: pl_fw=%s < min_fw=%s for %s+ min "
                    "(boot OTA budget %ss; file_done=%s new_telemetry=%s). "
                    "Next: dock WiFi/BLE OTA or USB — cellular boot path not completing."
                    % (
                        last_fw,
                        min_fw,
                        GIVE_UP_STUCK_MINUTES,
                        BOOT_OTA_MAX_S,
                        has_file_done,
                        has_new_telemetry,
                    )
                )
                try:
                    from sheets_config_upsert import upsert_config_keys

                    upsert_config_keys(
                        sheets,
                        sid,
                        [
                            ("ota_degraded", "1", "watch: cellular boot OTA stuck"),
                            (
                                "boot_ota_prefer_wifi",
                                "1",
                                "watch: prefer home Wi-Fi for boot OTA",
                            ),
                        ],
                    )
                    _log("ACTION set ota_degraded=1 boot_ota_prefer_wifi=1 (sheet)")
                except Exception as exc:
                    _log("ACTION escalate config failed: %s" % exc)
                give_up_logged = True
            elif stuck_min > 0 and stuck_min % 15 == 0 and stuck_min < GIVE_UP_STUCK_MINUTES:
                detail.append("ota_stuck %s min (give_up at %s)" % (stuck_min, GIVE_UP_STUCK_MINUTES))
    else:
        stuck_since = None
        give_up_logged = False

    summary = (
        "STATUS=%s min_fw=%s pl_fw=%s pl_ts=%s mode=%s | %s | last_event: %s"
        % (status, min_fw, last_fw, last_ts, last_mode, "; ".join(detail), last_ev_line)
    )
    _log(summary)

    try:
        STATE_PATH.write_text(
            json.dumps(
                {
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "min_fw": min_fw,
                    "power_log_fw": last_fw,
                    "power_log_ts": last_ts,
                    "lifecycle_fw": lifecycle_fw,
                    "ota_stuck_since_utc": stuck_since,
                    "give_up_logged": give_up_logged,
                    "summary": summary,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    return status


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--once", action="store_true")
    args = p.parse_args(argv)
    if args.once:
        poll_once()
        return 0
    _log("boat_p2_watch start interval=%ss" % args.interval)
    while True:
        try:
            poll_once()
        except Exception as exc:
            _log("ERROR poll: %s" % exc)
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    sys.exit(main() or 0)
