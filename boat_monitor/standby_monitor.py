"""
Standby operation: no BLE radio — automatic logging over Wi-Fi (cellular fallback).

Entered from main.py when switch/key are off and no USB host is connected.
Reboots when ble_policy.ble_wanted() becomes true so ble_service can start.
"""

import time

import auto_log
import ble_policy
import diag_log
from ble_service import log_power_and_gps, read_status


def main():
    diag_log.log("standby_monitor start")
    print("standby_monitor: BLE off — Wi-Fi-first auto-log")
    auto_log.load_persisted_overrides()
    interval_s = auto_log.interval_for_mode("docked_off")
    diag_log.log("docked interval_s=%s (after overrides)" % interval_s)
    last_auto_log_ms = time.ticks_add(time.ticks_ms(), -int(interval_s * 1000))
    last_auto_log_mode = None
    last_heartbeat_ms = time.ticks_ms()

    while True:
        if ble_policy.ble_wanted():
            diag_log.log("switch/key on -> reboot for BLE service")
            print("standby_monitor: switch/key on — rebooting for BLE service")
            import machine

            time.sleep(0.3)
            machine.reset()

        status = read_status()
        mode = status["mode"]
        now = time.ticks_ms()
        elapsed_s = time.ticks_diff(now, last_auto_log_ms) / 1000

        if time.ticks_diff(now, last_heartbeat_ms) > 60000:
            last_heartbeat_ms = now
            need = max(0, auto_log.interval_for_mode(mode) - elapsed_s)
            diag_log.log(
                "heartbeat mode=%s elapsed=%.0fs next_log_in~%.0fs v50=%s heap=%sK"
                % (mode, elapsed_s, need, status.get("v50"), diag_log.mem_kb())
            )

        if auto_log.should_log_now(mode, elapsed_s, last_auto_log_mode):
            last_auto_log_mode = mode
            last_auto_log_ms = now
            diag_log.log("auto-log START mode=%s elapsed=%.0fs" % (mode, elapsed_s))
            print("standby_monitor: auto-log mode=%s elapsed=%.0fs" % (mode, elapsed_s))
            try:
                summary = log_power_and_gps(note="auto_log", prefer_wifi=True, ble_monitor=None)
                diag_log.log("auto-log DONE %s" % summary)
                print("standby_monitor: auto-log result:", summary)
                print(
                    "standby_monitor: next auto-log in ~%ds (mode=%s)"
                    % (auto_log.interval_for_mode(mode), mode)
                )
            except Exception as exc:
                diag_log.log("auto-log FAIL %s" % exc)
                print("standby_monitor: auto-log failed:", exc)
                try:
                    diag_log.upload_tail_to_events()
                except Exception:
                    pass

        last_auto_log_mode = mode
        time.sleep(2)


if __name__ == "__main__":
    main()
