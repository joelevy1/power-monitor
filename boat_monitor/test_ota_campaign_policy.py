#!/usr/bin/env python3
"""Host checks for winter/dock campaign configuration guardrails."""

from __future__ import annotations

import tempfile
from pathlib import Path

import remote_boot_config
from apply_recovery_manifest import WINTER_HARDENING_PATHS, version_last
from apply_ship_config import profile_rows
from ota_stress_harness import ROOT, _ship_version, _uplink_matches
from ota_stress_rules import (
    DOCK_BOOT_START_TIMEOUT_S,
    DOCK_STRESS_KEYS,
    STALE_SHEET_KEYS,
)
from usb_recovery_push import RECOVERY_FILES


def main():
    dock = {key: value for key, value, _ in profile_rows("dock", "1.1.117")}
    assert dock["interval_engine_on_s"] == "600"
    assert dock["interval_engine_off_s"] == "3600"
    assert dock["min_fw_version"] == "1.1.117"

    underway = {key: value for key, value, _ in profile_rows("underway", "1.1.117")}
    assert underway["interval_engine_on_s"] == "60"
    assert underway["interval_engine_off_s"] == "300"

    assert _uplink_matches("Levy-Guest", "wifi")
    assert not _uplink_matches("cellular", "wifi")
    assert _uplink_matches("cellular", "cellular")
    assert version_last(("version.py", "cellular.py")) == ("cellular.py", "version.py")
    assert WINTER_HARDENING_PATHS[-1] == "version.py"
    assert "status_led.py" in RECOVERY_FILES

    version_before = (ROOT / "version.py").read_text(encoding="utf-8")
    manifest_before = (ROOT / "ota_manifest.json").read_text(encoding="utf-8")
    assert not _ship_version("9.9.9", allow_master_push=False)
    assert (ROOT / "version.py").read_text(encoding="utf-8") == version_before
    assert (ROOT / "ota_manifest.json").read_text(encoding="utf-8") == manifest_before

    dock_keys = {key: value for key, value, _ in DOCK_STRESS_KEYS}
    assert dock_keys["dock_mode"] == "home"
    assert dock_keys["standby_prefer_wifi"] == "1"
    assert "cmd_ota_force" in STALE_SHEET_KEYS
    assert "boat-p2:cmd_ota_force" in STALE_SHEET_KEYS
    assert DOCK_BOOT_START_TIMEOUT_S >= 3600 + 900

    original_path = remote_boot_config.PATH
    with tempfile.TemporaryDirectory() as tmp:
        remote_boot_config.PATH = str(Path(tmp) / "remote_boot_config.json")
        try:
            applied = remote_boot_config.apply_settings({"standby_prefer_wifi": "1"})
            assert "standby_prefer_wifi=1" in applied
            assert remote_boot_config.load()["standby_prefer_wifi"] is True
            assert remote_boot_config.effective_standby_log_prefer_wifi() is True

            remote_boot_config.apply_settings({"standby_prefer_wifi": "0"})
            assert remote_boot_config.load()["standby_prefer_wifi"] is False
            assert remote_boot_config.effective_standby_log_prefer_wifi() is False
        finally:
            remote_boot_config.PATH = original_path

    print("OTA campaign policy tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
