#!/usr/bin/env python3
"""Push standard field Config after a validated release.

NEVER run before validate_release.py --check-github passes on master.
min_fw_version is always set to VERSION in version.py (not a future PR version).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_config_upsert import upsert_config_keys  # noqa: E402
from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402


def _shipped_version():
    import version

    return getattr(version, "VERSION", "").strip()


def profile_rows(profile, version):
    if profile == "dock":
        intervals = [
            ("interval_engine_on_s", "600", "10 min while key_on during dock campaign"),
            ("interval_engine_off_s", "3600", "1 hour winter dock interval"),
        ]
    elif profile == "dock-stress":
        intervals = [
            ("interval_engine_on_s", "600", "10 min production key-on cadence"),
            ("interval_engine_off_s", "300", "5 min dock regression cadence"),
        ]
    elif profile == "switch-on":
        intervals = [
            ("interval_engine_on_s", "600", "10 min production switch-on cadence"),
            ("interval_engine_off_s", "3600", "1 hour production standby cadence"),
        ]
    else:
        intervals = [
            ("interval_engine_on_s", "60", "1 min while key_on (engine charging)"),
            ("interval_engine_off_s", "300", "5 min docked / standby battery test"),
        ]
    return intervals + [
        ("boot_ota_max_seconds", "420", "cellular full manifest needs 3–7 min"),
        ("min_fw_version", version, "OTA floor (= GitHub master manifest %s)" % version),
    ]


def _stage_wifi_feature_prerequisites(sheets, sid, profile, version):
    """Stage transport only; the target is deliberately not dispatched yet."""
    rows = [
        row
        for row in profile_rows(profile, version)
        if row[0] != "min_fw_version"
    ]
    rows.extend(
        [
            (
                "boot_ota_prefer_wifi",
                "1",
                "apply_ship_config: prerequisite for multi-file OTA",
            ),
            (
                "auto_ota_on_boot",
                "0",
                "apply_ship_config: hold target until transport acknowledgement",
            ),
            (
                "clear_pending_ota",
                "1",
                "apply_ship_config: clear request before transport staging",
            ),
        ]
    )
    upsert_config_keys(sheets, sid, rows)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply validated release settings to the boat sheet")
    parser.add_argument(
        "--profile",
        choices=("underway", "switch-on", "dock-stress", "dock"),
        default="underway",
        help="preserve the intended logging cadence while setting min_fw",
    )
    args = parser.parse_args(argv)
    v = _shipped_version()
    if not v:
        print("Missing VERSION in version.py", file=sys.stderr)
        return 1

    script = Path(__file__).resolve().parent / "validate_release.py"
    for extra in ([], ["--check-github"]):
        cmd = [sys.executable, str(script)] + extra
        r = subprocess.run(cmd, check=False)
        if r.returncode != 0:
            print(
                "apply_ship_config: validate_release failed — fix release before sheet min_fw",
                file=sys.stderr,
            )
            return r.returncode

    creds_path = _credentials_path()
    if not creds_path:
        print("Missing service account credentials", file=sys.stderr)
        return 1

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)

    from ota_stress_rules import (
        STALE_SHEET_KEYS,
        device_config_acknowledged,
        latest_power_log_uses_wifi,
        manifest_requires_wifi,
    )

    manifest = json.loads(
        (Path(__file__).resolve().parent / "ota_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    wifi_feature = manifest_requires_wifi(manifest)
    if wifi_feature:
        transport_ack = device_config_acknowledged(
            sheets,
            sid,
            "boot_ota_prefer_wifi",
            "1",
        )
        wifi_healthy = latest_power_log_uses_wifi(sheets, sid)
        if not transport_ack or not wifi_healthy:
            _stage_wifi_feature_prerequisites(sheets, sid, args.profile, v)
            clear_rows = [
                (k, "", "apply_ship_config: clear one-shot while staging transport")
                for k in STALE_SHEET_KEYS
            ]
            upsert_config_keys(sheets, sid, clear_rows)
            print(
                "HOLD: multi-file OTA target was not queued "
                "(transport_ack=%s wifi_healthy=%s)."
                % (transport_ack, wifi_healthy)
            )
            print(
                "Wait for a remote_config event with boot_ota_prefer_wifi=1 "
                "and a Wi-Fi Power_Log, then rerun this command."
            )
            return 2

    rows = profile_rows(args.profile, v)
    if wifi_feature:
        rows.extend(
            [
                (
                    "auto_ota_on_boot",
                    "1",
                    "apply_ship_config: dispatch after Wi-Fi transport acknowledgement",
                ),
                (
                    "clear_pending_ota",
                    "",
                    "apply_ship_config: prerequisite acknowledged",
                ),
            ]
        )
    upsert_config_keys(sheets, sid, rows)

    clear_rows = [(k, "", "apply_ship_config: clear one-shot") for k in STALE_SHEET_KEYS]
    upsert_config_keys(sheets, sid, clear_rows)

    for key, val, _ in rows:
        print("OK:", key, "=", val)
    print("Sheet updated. Pico OTA when current < min_fw after master manifest ships.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
