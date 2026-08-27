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
    device_config_acknowledged,
    latest_power_log_uses_wifi,
    manifest_requires_wifi,
)
from usb_recovery_push import RECOVERY_FILES


class _FakeSheets:
    def __init__(self, ranges):
        self.ranges = ranges
        self.requested_range = None

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId=None, range=None):
        self.requested_range = range
        return self

    def execute(self):
        return {"values": self.ranges.get(self.requested_range, [])}


def main():
    dock = {key: value for key, value, _ in profile_rows("dock", "1.1.117")}
    assert dock["interval_engine_on_s"] == "600"
    assert dock["interval_engine_off_s"] == "3600"
    assert dock["min_fw_version"] == "1.1.117"

    underway = {key: value for key, value, _ in profile_rows("underway", "1.1.117")}
    assert underway["interval_engine_on_s"] == "60"
    assert underway["interval_engine_off_s"] == "300"

    switch_on = {
        key: value for key, value, _ in profile_rows("switch-on", "1.1.117")
    }
    assert switch_on["interval_engine_on_s"] == "600"
    assert switch_on["interval_engine_off_s"] == "3600"
    assert switch_on["min_fw_version"] == "1.1.117"

    dock_stress = {
        key: value for key, value, _ in profile_rows("dock-stress", "1.1.117")
    }
    assert dock_stress["interval_engine_on_s"] == "600"
    assert dock_stress["interval_engine_off_s"] == "300"

    assert _uplink_matches("Levy-Guest", "wifi")
    assert not _uplink_matches("cellular", "wifi")
    assert _uplink_matches("cellular", "cellular")
    assert version_last(("version.py", "cellular.py")) == ("cellular.py", "version.py")
    assert WINTER_HARDENING_PATHS[-1] == "version.py"
    assert "status_led.py" in RECOVERY_FILES
    usb_batch = (ROOT / "run_usb_ota_self_sufficient.bat").read_text(
        encoding="utf-8"
    )
    assert "--ota-self-sufficient" in usb_batch
    assert "--enable-boot-ota" not in usb_batch
    usb_patch = (ROOT / "usb_recovery_patch.py").read_text(encoding="utf-8")
    assert "PENDING_OTA_ON_BOOT = False" in usb_patch
    assert "AUTO_OTA_ON_BOOT = False" in usb_patch
    assert 'DOCK_MODE = "home"' in usb_patch
    assert 'OTA_MANIFEST_PROFILE = "feature-pack"' in usb_patch
    assert "STANDBY_PREFER_WIFI = True" in usb_patch
    usb_push = (ROOT / "usb_recovery_push.py").read_text(encoding="utf-8")
    assert (
        'auto_ota = "True" if args.enable_boot_ota else "False"'
        in usb_push
    )
    assert 'DOCK_MODE = \\"away\\"' not in usb_push

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
    assert not manifest_requires_wifi({"files": [{}, {}]})
    assert manifest_requires_wifi({"files": [{}, {}, {}]})
    fake = _FakeSheets(
        {
            "Events!A2:D": [
                ["t1", "boat-p2", "remote_config", "boot_ota_prefer_wifi=0"],
                ["t2", "boat-p2", "remote_config", "boot_ota_prefer_wifi=1"],
            ],
            "Power_Log!1:1": [["ts", "device_id", "mode", "uplink"]],
            "Power_Log!A2:Z": [
                ["t1", "boat-p2", "docked_off", "cellular"],
                ["t2", "boat-p2", "docked_off", "Levy-Guest"],
            ],
        }
    )
    assert device_config_acknowledged(
        fake, "sheet", "boot_ota_prefer_wifi", "1"
    )
    assert latest_power_log_uses_wifi(fake, "sheet")
    harness_source = (ROOT / "ota_stress_harness.py").read_text(encoding="utf-8")
    assert "upsert_clear_pending" not in harness_source
    assert 'print("Bootstrap-rules skip: explicitly disabled")' in harness_source
    ship_source = (ROOT / "apply_ship_config.py").read_text(encoding="utf-8")
    assert "_stage_wifi_feature_prerequisites" in ship_source
    assert "transport_ack" in ship_source
    assert "wifi_healthy" in ship_source
    assert "HOLD: multi-file OTA target was not queued" in ship_source
    overnight_source = (ROOT / "overnight_dock_campaign.py").read_text(
        encoding="utf-8"
    )
    assert 'mode == "docked_off"' in overnight_source
    assert 'uplink != "cellular"' in overnight_source
    assert '"dock-stress"' in overnight_source
    assert "restore_production()" in overnight_source

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
