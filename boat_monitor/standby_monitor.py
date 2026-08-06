"""
Standby operation: no BLE radio — automatic logging over Wi-Fi (cellular fallback).

Entered from main.py when switch/key are off and no USB host is connected.
Reboots when ble_policy.ble_wanted() becomes true so ble_service can start.
"""

import time

import auto_log
import ble_policy
from ble_service import log_power_and_gps, read_status


def main():
    print("standby_monitor: BLE off — Wi-Fi-first auto-log")
    last_auto_log_ms = time.ticks_ms()
    last_auto_log_mode = None

    while True:
        if ble_policy.ble_wanted():
            print("standby_monitor: switch/key/USB — rebooting for BLE service")
            import machine

            time.sleep(0.3)
            machine.reset()

        status = read_status()
        mode = status["mode"]
        now = time.ticks_ms()
        elapsed_s = time.ticks_diff(now, last_auto_log_ms) / 1000

        if auto_log.should_log_now(mode, elapsed_s, last_auto_log_mode):
            last_auto_log_mode = mode
            last_auto_log_ms = now
            print("standby_monitor: auto-log mode=%s elapsed=%.0fs" % (mode, elapsed_s))
            try:
                summary = log_power_and_gps(note="auto_log", prefer_wifi=True, ble_monitor=None)
                print("standby_monitor: auto-log result:", summary)
            except Exception as exc:
                print("standby_monitor: auto-log failed:", exc)

        last_auto_log_mode = mode
        time.sleep(2)


if __name__ == "__main__":
    main()
