#!/usr/bin/env python3
"""Static host guards for BLE behavior that depends on MicroPython hardware."""

from pathlib import Path


def main():
    source = (Path(__file__).resolve().parent / "ble_service.py").read_text(
        encoding="utf-8"
    )
    init = source.split("class BoatMonitorBle:", 1)[1].split(
        "def irq", 1
    )[0]
    assert init.index("auto_log.load_persisted_overrides()") < init.index(
        "bluetooth.BLE()"
    )
    update = source.split("def update_status", 1)[1].split(
        "def handle_command", 1
    )[0]
    assert "for conn in tuple(self.connections)" in update
    assert "BLE_NOTIFY_FAILURE_LIMIT" in update
    assert "failures >= BLE_NOTIFY_FAILURE_LIMIT" in update
    assert "self.connections.discard(conn)" in update
    assert update.index("self.connections.discard(conn)") < update.index(
        "self.advertise()"
    )

    log_command = source.split('elif cmd in ("log", "log_now"):', 1)[1].split(
        'elif cmd in ("diag", "upload_diag"):', 1
    )[0]
    assert "BLE_LOG_REQUEST_PATH" in log_command
    assert 'self.command_result = "logging_handoff"' in log_command
    assert log_command.index("self.update_status()") < log_command.index(
        "machine.reset()"
    )

    main = source.split("def main():", 1)[1].split(
        'if __name__ == "__main__":', 1
    )[0]
    assert main.index("resilience.enable_watchdog()") < main.index(
        "BoatMonitorBle().run()"
    )

    advertise = source.split("def advertise(self, refresh=False):", 1)[1].split(
        "def update_status", 1
    )[0]
    assert "self.ble.gap_advertise(None)" in advertise
    assert "BLE_ADV_FAILURE_RESET_COUNT" in advertise
    assert "machine.reset()" in advertise
    run_loop = source.split("def run(self):", 1)[1].split("def main():", 1)[0]
    assert "BLE_ADV_REFRESH_MS" in run_loop
    assert "self.advertise(refresh=True)" in run_loop
    assert "BLE_CONNECTED_SENSOR_REFRESH_MS" in run_loop
    assert "read_sensors = not self.connections" in run_loop
    assert "self._last_sensor_refresh_ms = now_ms" in run_loop
    auto_log = source.split("def _maybe_auto_log", 1)[1].split(
        "def run(self):", 1
    )[0]
    assert "BLE auto-log complete; rebooting to reclaim network modules" in auto_log
    assert "gc.mem_free()" not in auto_log
    assert "machine.reset()" in auto_log
    on_connect = source.split("def _scheduled_on_connect", 1)[1].split(
        "def _scheduled_conn_params", 1
    )[0]
    assert "BLE_CONNECT_MIN_HEAP_BYTES" in on_connect
    assert "rebooting_low_heap:" in on_connect
    assert on_connect.index("self.update_status(sensors=False)") < on_connect.index(
        "machine.reset()"
    )
    reboot = source.split('elif cmd == "reboot":', 1)[1].split(
        'elif cmd in ("wifi", "start_wifi"):', 1
    )[0]
    assert "set_pending_ota" not in reboot
    ota = source.split('elif cmd in ("ota", "ota_check"):', 1)[1].split(
        'elif cmd in ("log", "log_now"):', 1
    )[0]
    assert "set_pending_ota(True)" in ota
    wifi = source.split('elif cmd in ("wifi", "start_wifi"):', 1)[1].split(
        'elif cmd in ("ota", "ota_check"):', 1
    )[0]
    assert 'self.command_result = "wifi_console_disabled"' in wifi
    assert "wifi_mode.txt" not in wifi
    assert "machine.reset()" not in wifi
    signal = source.split(
        'elif cmd in ("signal", "modem_status", "cell_status"):', 1
    )[1].split('elif cmd in ("gps", "check_gps", "gps_status"):', 1)[0]
    assert 'signal_check_disabled: use Log Now' in signal
    assert "Sim7600Modem" not in signal

    print("BLE service regression guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
