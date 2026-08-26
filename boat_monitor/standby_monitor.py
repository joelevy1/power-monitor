"""
Standby operation: no BLE radio — automatic logging over Wi-Fi (cellular fallback).

Entered from main.py when switch/key are off and no USB host is connected.
Reboots when ble_policy.ble_wanted() becomes true so the BLE service can start.
"""

import time

import auto_log
import ble_policy
import diag_log
import resilience
from boat_status import read_status


# Minutes after an auto-log attempt before we probe the modem (logging can
# take 10-90s on cellular + GPS).
MODEM_WATCHDOG_QUIET_S = 150

# Minimum gap between auto-log attempts after a failure (success resets the
# Config interval timer via last_successful_log_ms).
MIN_ATTEMPT_GAP_S = 60
MIN_ATTEMPT_GAP_ENOMEM_S = 30
# Consecutive soft-fails before stall reboot (also triggers degraded Events).
AUTO_LOG_FAIL_REBOOT_COUNT = 4
DOCK_LOG_REQUEST_PATH = "dock_log_request.flag"

_transition_pins = []
_transition_scheduled = False
_micropython = None


def _transition_to_ble(_arg=0):
    """Leave a blocking standby network operation when switch/key turns on."""
    global _transition_scheduled
    if not ble_policy.ble_wanted():
        _transition_scheduled = False
        return
    try:
        diag_log.log("switch/key IRQ -> teardown Wi-Fi then reboot for BLE service")
    except Exception:
        pass
    try:
        import wifi_uplink

        wifi_uplink.ensure_wifi_off()
    except Exception as exc:
        try:
            diag_log.log("BLE IRQ Wi-Fi teardown warning: %s" % exc)
        except Exception:
            pass
    try:
        time.sleep_ms(300)
    except AttributeError:
        time.sleep(0.3)
    import machine

    machine.reset()


def _ble_input_irq(_pin):
    global _transition_scheduled
    if _transition_scheduled:
        return
    _transition_scheduled = True
    try:
        _micropython.schedule(_transition_to_ble, 0)
    except Exception:
        _transition_scheduled = False


def _arm_ble_transition_irq():
    """Watch active-low switch/key even while Wi-Fi or cellular calls block."""
    global _micropython
    try:
        import config
        import machine
        import micropython

        _micropython = micropython
        for pin_num in (config.PIN_BATTERY_SWITCH, config.PIN_KEY):
            pin = machine.Pin(pin_num, machine.Pin.IN, machine.Pin.PULL_UP)
            pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=_ble_input_irq)
            _transition_pins.append(pin)
        if ble_policy.ble_wanted():
            _transition_to_ble()
        return True
    except Exception as exc:
        diag_log.log("BLE transition IRQ unavailable: %s" % exc)
        return False


def _standby_prefer_wifi():
    """Wi-Fi-first standby logs at dock; independent of boot OTA transport."""
    try:
        import remote_boot_config

        return remote_boot_config.effective_standby_log_prefer_wifi()
    except Exception:
        return False


def _reboot_after_stall(reason, mode, device_id):
    resilience.reboot_after_stall(device_id, reason, mode=mode)


def _in_progress_limit_s(mode):
    """Single auto-log session should finish well within 2× the log interval."""
    return auto_log.stale_reboot_threshold_s(mode)


def _firmware_upgrade_pending():
    """Skip heavy logs only when boot OTA will actually run on next reboot."""
    try:
        import remote_boot_config

        return remote_boot_config.should_run_boot_ota()
    except Exception:
        return False


def _reboot_for_pending_upgrade(source):
    try:
        import ota_reboot

        return ota_reboot.reboot_if_upgrade_pending(source=source)
    except Exception:
        return False


def _boot_log_wanted():
    """One sheet row right after standby starts so boot is visible without waiting an interval."""
    if _firmware_upgrade_pending():
        return False
    return True


def _finish_log_session(device_id, mode, summary, source):
    try:
        import remote_telemetry

        remote_telemetry.after_logging_session(
            device_id, mode, summary, prefer_wifi=_standby_prefer_wifi()
        )
    except Exception as exc:
        diag_log.log("after_logging_session skipped: %s" % exc)
    try:
        import ota_reboot

        ota_reboot.reboot_if_upgrade_pending(source=source)
    except Exception:
        pass


def main(skip_boot_log=False):
    diag_log.log("standby_monitor start skip_boot_log=%s" % skip_boot_log)
    resilience.enable_watchdog()
    _arm_ble_transition_irq()
    print("standby_monitor: BLE off — auto-log (Wi-Fi or cellular per remote_boot_config)")
    auto_log.load_persisted_overrides()
    try:
        import remote_boot_config

        remote_boot_config.apply_persisted_log_intervals()
    except Exception:
        pass
    interval_s = auto_log.interval_for_mode("docked_off")
    diag_log.log("docked interval_s=%s (after overrides)" % interval_s)
    now_boot = time.ticks_ms()
    # Schedule from last *successful* sheet row so Config intervals match what
    # you see in Power_Log (failed/hung cycles retry without waiting another
    # full interval from a doomed attempt start).
    if skip_boot_log:
        last_successful_log_ms = now_boot
        last_attempt_ms = now_boot
        last_auto_log_mode = "docked_off"
    else:
        last_successful_log_ms = time.ticks_add(
            now_boot, -int(interval_s * 1000)
        )
        last_attempt_ms = time.ticks_add(
            now_boot, -int(MIN_ATTEMPT_GAP_S * 1000)
        )
        last_auto_log_mode = None
    last_heartbeat_ms = now_boot
    last_modem_watchdog_ms = now_boot
    auto_log_failures = 0
    auto_log_started_ms = None
    device_id = "boat-p2"

    if _firmware_upgrade_pending():
        diag_log.log("standby: upgrade pending — skip boot_log, reboot for boot OTA")
        if _reboot_for_pending_upgrade("standby_boot_skip_log"):
            return

    if not skip_boot_log and _boot_log_wanted():
        try:
            from log_session import log_power_and_gps

            status = read_status()
            mode = status["mode"]
            device_id = status.get("device") or device_id
            diag_log.log("boot_log START mode=%s" % mode)
            print("standby_monitor: boot_log (online heartbeat)")
            summary = log_power_and_gps(
                note="boot_log",
                prefer_wifi=_standby_prefer_wifi(),
                ble_monitor=None,
                periodic_cellular_sync=True,
            )
            diag_log.log("boot_log DONE %s" % summary)
            print("standby_monitor: boot_log result:", summary)
            now_boot = time.ticks_ms()
            last_attempt_ms = now_boot
            if summary and str(summary).startswith("power: ok"):
                last_successful_log_ms = now_boot
                auto_log_failures = 0
            else:
                auto_log_failures = 1
            _finish_log_session(device_id, mode, summary, "standby_boot_log")
            last_auto_log_mode = mode
        except Exception as exc:
            auto_log_failures = 1
            diag_log.log("boot_log FAIL %s" % exc)
            print("standby_monitor: boot_log failed:", exc)

    while True:
        if ble_policy.ble_wanted():
            diag_log.log("switch/key on -> teardown Wi-Fi then reboot for BLE service")
            print("standby_monitor: switch/key on — stopping Wi-Fi before BLE reboot")
            try:
                import wifi_uplink

                wifi_uplink.ensure_wifi_off()
            except Exception as exc:
                diag_log.log("BLE transition Wi-Fi teardown warning: %s" % exc)
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            # CYW43439 is a separate chip and survives an RP2040 software
            # reset. Give deinit time to complete before main.py starts BLE.
            time.sleep(1.0)
            import machine

            machine.reset()

        status = read_status()
        mode = status["mode"]
        device_id = status.get("device") or device_id
        now = time.ticks_ms()
        since_success_s = time.ticks_diff(now, last_successful_log_ms) / 1000
        stale_limit_s = auto_log.stale_reboot_threshold_s(mode)

        if time.ticks_diff(now, last_heartbeat_ms) > 60000:
            last_heartbeat_ms = now
            need = max(0, auto_log.interval_for_mode(mode) - since_success_s)
            diag_log.log(
                "heartbeat mode=%s since_success=%.0fs next_log_in~%.0fs stale_limit=%ss v50=%s heap=%sK"
                % (mode, since_success_s, need, stale_limit_s, status.get("v50"), diag_log.mem_kb())
            )
            try:
                import v50_energy

                v50_energy.tick(status.get("v50"))
            except Exception:
                pass
            try:
                import power_transition

                power_transition.maybe_reboot_on_power_transition(status, mode)
            except Exception:
                pass
            try:
                import remote_telemetry

                remote_telemetry.maybe_report_standby_overdue(
                    device_id,
                    mode,
                    since_success_s,
                    auto_log.interval_for_mode(mode),
                )
                remote_telemetry.maybe_standby_heartbeat(device_id, mode, prefer_wifi=True)
            except Exception as exc:
                diag_log.log("standby_overdue telemetry skipped: %s" % exc)

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

        if (
            since_success_s >= MODEM_WATCHDOG_QUIET_S
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

        since_attempt_s = time.ticks_diff(now, last_attempt_ms) / 1000
        min_gap = MIN_ATTEMPT_GAP_S
        if auto_log_failures > 0:
            min_gap = MIN_ATTEMPT_GAP_ENOMEM_S

        if (
            auto_log_started_ms is None
            and since_attempt_s >= min_gap
            and auto_log.should_log_now(mode, since_success_s, last_auto_log_mode)
        ):
            if _firmware_upgrade_pending():
                diag_log.log(
                    "standby: upgrade pending — skip auto_log, reboot for boot OTA"
                )
                if _reboot_for_pending_upgrade("standby_auto_log_skip"):
                    continue
                time.sleep(30)
                continue
            try:
                with open(DOCK_LOG_REQUEST_PATH, "w") as request_file:
                    request_file.write("1")
            except Exception as exc:
                diag_log.log("dock log request write failed: %s" % exc)
                time.sleep(30)
                continue
            diag_log.log(
                "dock log due mode=%s since_success=%.0fs -> fresh-heap reboot"
                % (mode, since_success_s)
            )
            print("standby_monitor: rebooting for fresh-heap dock log")
            time.sleep(0.3)
            import machine

            machine.reset()

        last_auto_log_mode = mode
        resilience.feed_watchdog()
        try:
            import status_led

            status_led.tick()
        except Exception:
            pass
        time.sleep(2)


if __name__ == "__main__":
    main()
