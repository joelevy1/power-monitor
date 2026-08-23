#!/usr/bin/env python3
"""Static host guards for BLE behavior that depends on MicroPython hardware."""

from pathlib import Path


def main():
    source = (Path(__file__).resolve().parent / "ble_service.py").read_text(
        encoding="utf-8"
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
    assert "resilience.set_service_hook(" in log_command
    assert "lambda: self.update_status(sensors=False)" in log_command
    assert "resilience.set_service_hook(None)" in log_command

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
    auto_log = source.split("def _maybe_auto_log", 1)[1].split(
        "def run(self):", 1
    )[0]
    assert "BLE_AUTO_LOG_RECYCLE_HEAP_BYTES" in auto_log
    assert auto_log.index("gc.collect()") < auto_log.index("machine.reset()")
    assert "BLE_LOG_COMMAND_DEADLINE_MS" in log_command
    assert "_arm_command_deadline(BLE_LOG_COMMAND_DEADLINE_MS)" in log_command
    assert "_cancel_command_deadline()" in log_command
    deadline = source.split("def _command_deadline_expired", 1)[1].split(
        "def _arm_command_deadline", 1
    )[0]
    assert "machine.reset()" in deadline
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

    print("BLE service regression guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
