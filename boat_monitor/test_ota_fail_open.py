#!/usr/bin/env python3
"""Regression guards for escaping boot OTA memory failures into normal service."""

from pathlib import Path

import ota_health


def main():
    root = Path(__file__).resolve().parent
    source = (root / "main.py").read_text(
        encoding="utf-8"
    )
    assert "pause_after_ota_memory_failure" in source
    assert "pause_after_terminal_ota_failure" in source
    assert "pause_after_retry_limit" in source
    assert "terminal_ota_error" in source
    assert "boot_retry_allowed" in source
    assert "boot OTA Wi-Fi ENOMEM" not in source
    assert source.index("_ota_tls_reserve = bytearray(48 * 1024)") < source.index(
        "STANDBY_CLEAN_BOOT_PATH"
    )
    before_update = source.split("success = ota.update(", 1)[0]
    boot_ota = before_update.split("if _boot_ota_wanted:", 1)[1]
    assert "upload_bounded(" not in boot_ota
    assert "flush_pending_on_boot()" not in boot_ota
    no_ota = source.split("if not _boot_ota_wanted:", 1)[1].split(
        "if _boot_ota_wanted:", 1
    )[0]
    assert "flush_pending_on_boot()" in no_ota
    assert "flush_ota_events_uplink" not in source
    ota_source = (root / "ota.py").read_text(encoding="utf-8")
    reboot_success = ota_source.split("if reboot:", 1)[1].split(
        "return True", 1
    )[0]
    assert "record_boot_ota_result(" in reboot_success
    assert 'emit=False' in reboot_success
    assert reboot_success.index("clear_pending_ota()") < reboot_success.index(
        "\n            machine.reset()"
    )
    assert "queue_result(" in reboot_success
    assert "report_boot_ota(" not in reboot_success
    update_source = ota_source.split("def update(", 1)[1].split(
        "def check(", 1
    )[0]
    ota_failure = update_source.rsplit("except Exception as exc:", 1)[1].split(
        "finally:", 1
    )[0]
    assert "upload_bounded(" not in ota_failure
    assert "ota_trace.queue(" in ota_failure
    deferred = source.split("if _deferred_ble_log:", 1)[1].split(
        "# Decide which mode was requested", 1
    )[0]
    assert deferred.index("_os.remove(BLE_LOG_REQUEST_PATH)") < deferred.index(
        "_deferred_log("
    )
    assert "BLE_LOG_DEADLINE_MS" in deferred
    assert "_ble_log_resilience.set_service_hook(_ble_log_deadline)" in deferred
    assert "with open(BLE_LOG_RESULT_PATH" in deferred
    assert deferred.rindex("_ble_log_machine.reset()") > deferred.index(
        "_deferred_log("
    )
    assert ota_health.terminal_ota_error(
        "manifest_tier_max_2_files_cellular"
    )
    assert ota_health.terminal_ota_error(
        "manifest_kind_wifi-feature_cellular_blocked"
    )
    assert not ota_health.terminal_ota_error("Wi-Fi could not connect")
    print("OTA fail-open recovery guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
