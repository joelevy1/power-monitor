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


# Minutes after an auto-log attempt before we probe the modem (logging can
# take 10-90s on cellular + GPS).
MODEM_WATCHDOG_QUIET_S = 150

# Consecutive auto-log failures (exceptions or power: failed) before reboot.
AUTO_LOG_FAIL_REBOOT_COUNT = 3


def _reboot_after_stall(reason, mode, device_id):
    diag_log.upload_stall_report(device_id, reason, mode=mode)
    import machine

    time.sleep(0.5)
    machine.reset()


def _in_progress_limit_s(mode):
    """Single auto-log session should finish well within 2× the log interval."""
    return auto_log.stale_reboot_threshold_s(mode)


def main():
    diag_log.log("standby_monitor start")
    print("standby_monitor: BLE off — Wi-Fi-first auto-log")
    auto_log.load_persisted_overrides()
    interval_s = auto_log.interval_for_mode("docked_off")
    diag_log.log("docked interval_s=%s (after overrides)" % interval_s)
    last_auto_log_ms = time.ticks_add(time.ticks_ms(), -int(interval_s * 1000))
    last_auto_log_mode = None
    last_heartbeat_ms = time.ticks_ms()
    last_modem_watchdog_ms = time.ticks_ms()
    last_successful_log_ms = time.ticks_ms()
    auto_log_failures = 0
    auto_log_started_ms = None
    device_id = "boat-p2"

    while True:
        if ble_policy.ble_wanted():
            diag_log.log("switch/key on -> reboot for BLE service")
            print("standby_monitor: switch/key on — rebooting for BLE service")
            import machine

            time.sleep(0.3)
            machine.reset()

        status = read_status()
        mode = status["mode"]
        device_id = status.get("device") or device_id
        now = time.ticks_ms()
        elapsed_s = time.ticks_diff(now, last_auto_log_ms) / 1000
        stale_limit_s = auto_log.stale_reboot_threshold_s(mode)

        if time.ticks_diff(now, last_heartbeat_ms) > 60000:
            last_heartbeat_ms = now
            need = max(0, auto_log.interval_for_mode(mode) - elapsed_s)
            diag_log.log(
                "heartbeat mode=%s elapsed=%.0fs next_log_in~%.0fs stale_limit=%ss v50=%s heap=%sK"
                % (mode, elapsed_s, need, stale_limit_s, status.get("v50"), diag_log.mem_kb())
            )
            stale_s = time.ticks_diff(now, last_successful_log_ms) / 1000
            if stale_s >= stale_limit_s:
                reason = (
                    "no successful auto-log for %.0fs (limit 2x interval = %ss)"
                    % (stale_s, stale_limit_s)
                )
                print("standby_monitor: %s — rebooting" % reason)
                _reboot_after_stall(reason, mode, device_id)

        if auto_log_started_ms is not None:
            running_s = time.ticks_diff(now, auto_log_started_ms) / 1000
            run_limit_s = _in_progress_limit_s(mode)
            if running_s >= run_limit_s:
                reason = "auto-log running %.0fs (limit %ss)" % (running_s, run_limit_s)
                print("standby_monitor: %s — rebooting" % reason)
                _reboot_after_stall(reason, mode, device_id)

        since_log_s = time.ticks_diff(now, last_auto_log_ms) / 1000
        if (
            since_log_s >= MODEM_WATCHDOG_QUIET_S
            and time.ticks_diff(now, last_modem_watchdog_ms) >= 300000
        ):
            last_modem_watchdog_ms = now
            try:
                import cellular

                if cellular.modem_uart_responds():
                    diag_log.log(
                        "WARN modem AT responded in standby (expected off) — AT+CPOF"
                    )
                    print("standby_monitor: unexpected modem awake — powering off")
                    try:
                        cellular.Sim7600Modem().power_off()
                        diag_log.log("modem watchdog power_off done")
                    except Exception as exc:
                        diag_log.log("modem watchdog power_off failed: %s" % exc)
                        print("standby_monitor: modem power_off failed:", exc)
            except Exception as exc:
                diag_log.log("modem watchdog skipped: %s" % exc)

        if auto_log.should_log_now(mode, elapsed_s, last_auto_log_mode):
            last_auto_log_mode = mode
            last_auto_log_ms = now
            auto_log_started_ms = now
            diag_log.log("auto-log START mode=%s elapsed=%.0fs" % (mode, elapsed_s))
            print("standby_monitor: auto-log mode=%s elapsed=%.0fs" % (mode, elapsed_s))
            try:
                summary = log_power_and_gps(note="auto_log", prefer_wifi=True, ble_monitor=None)
                auto_log_started_ms = None
                diag_log.log("auto-log DONE %s" % summary)
                print("standby_monitor: auto-log result:", summary)
                if summary and str(summary).startswith("power: ok"):
                    last_successful_log_ms = time.ticks_ms()
                    auto_log_failures = 0
                else:
                    auto_log_failures += 1
                    diag_log.log("auto-log soft-fail count=%s" % auto_log_failures)
                if auto_log_failures >= AUTO_LOG_FAIL_REBOOT_COUNT:
                    reason = "auto-log failed %s times in a row" % auto_log_failures
                    print("standby_monitor: %s — rebooting" % reason)
                    _reboot_after_stall(reason, mode, device_id)
                print(
                    "standby_monitor: next auto-log in ~%ds (mode=%s)"
                    % (auto_log.interval_for_mode(mode), mode)
                )
            except Exception as exc:
                auto_log_started_ms = None
                auto_log_failures += 1
                diag_log.log("auto-log FAIL %s count=%s" % (exc, auto_log_failures))
                print("standby_monitor: auto-log failed:", exc)
                try:
                    diag_log.upload_tail_to_events(device=device_id, lines=25)
                except Exception:
                    pass
                if auto_log_failures >= AUTO_LOG_FAIL_REBOOT_COUNT:
                    reason = "auto-log exception x%s last=%s" % (auto_log_failures, exc)
                    print("standby_monitor: %s — rebooting" % reason)
                    _reboot_after_stall(reason, mode, device_id)

        last_auto_log_mode = mode
        time.sleep(2)


if __name__ == "__main__":
    main()
