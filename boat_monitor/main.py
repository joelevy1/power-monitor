STANDBY_CLEAN_BOOT_PATH = "standby_clean_boot.flag"  # legacy 1.1.159 marker
DOCK_LOG_REQUEST_PATH = "dock_log_request.flag"
STANDBY_AFTER_LOG_PATH = "standby_after_log.flag"
DOCK_LOG_DEADLINE_MS = 180000

_dock_log_requested = False
_standby_after_log = False
try:
    import os as _early_os

    for _request_path in (DOCK_LOG_REQUEST_PATH, STANDBY_CLEAN_BOOT_PATH):
        try:
            _early_os.stat(_request_path)
            _early_os.remove(_request_path)
            _dock_log_requested = True
        except OSError:
            pass
    try:
        _early_os.stat(STANDBY_AFTER_LOG_PATH)
        _early_os.remove(STANDBY_AFTER_LOG_PATH)
        _standby_after_log = True
    except OSError:
        pass
except Exception:
    pass

if _dock_log_requested:
    # Consume the request before networking. If the deadline/watchdog resets,
    # the next boot enters idle standby rather than retrying in a tight loop.
    try:
        with open(STANDBY_AFTER_LOG_PATH, "w") as _after_log_marker:
            _after_log_marker.write("1")
    except Exception:
        pass
    import time as _dock_time
    import resilience as _dock_resilience

    _dock_resilience.enable_watchdog()
    _dock_started_ms = _dock_time.ticks_ms()

    def _dock_log_deadline():
        if (
            _dock_time.ticks_diff(_dock_time.ticks_ms(), _dock_started_ms)
            >= DOCK_LOG_DEADLINE_MS
        ):
            import machine as _dock_deadline_machine

            _dock_deadline_machine.reset()

    _dock_resilience.set_service_hook(_dock_log_deadline)
    try:
        from log_session import log_power_and_gps as _dock_log_once

        _dock_result = _dock_log_once(
            "auto_log",
            gps_timeout_s=10,
            prefer_wifi=True,
            ble_monitor=None,
            periodic_cellular_sync=True,
        )
        print("dock log handoff:", _dock_result)
    except Exception as _dock_exc:
        print("dock log handoff failed:", _dock_exc)
    finally:
        _dock_resilience.set_service_hook(None)
        try:
            import wifi_uplink as _dock_wifi

            _dock_wifi.ensure_wifi_off()
        except Exception as _wifi_shutdown_exc:
            print("dock Wi-Fi shutdown before reset:", _wifi_shutdown_exc)
        import machine as _dock_machine

        # CYW43439 survives RP2040 reset; allow STA deinit to settle so the
        # next fresh boot does not inherit stale association/driver state.
        _dock_time.sleep(1)
        _dock_machine.reset()

if _standby_after_log:
    # A pending OTA must run through normal main before returning to standby.
    try:
        import remote_boot_config as _early_rbc

        _standby_can_idle = not _early_rbc.should_run_boot_ota()
    except Exception:
        _standby_can_idle = True
    if _standby_can_idle:
        import standby_monitor as _early_standby

        _early_standby.main(skip_boot_log=True)

try:
    import gc

    gc.collect()
except Exception:
    pass

try:
    import diag_log
    import version

    diag_log.log("main boot fw=%s" % getattr(version, "VERSION", "?"))
    try:
        import status_led

        status_led.set_mode("boot")
    except Exception:
        pass
except Exception:
    pass

try:
    import ota_config
    import remote_boot_config

    _boot_ota_wanted = remote_boot_config.should_run_boot_ota()
    if not _boot_ota_wanted:
        # Never open a telemetry transport before OTA. Cellular/TLS imports
        # fragment the fresh boot heap needed by a subsequent Wi-Fi TLS socket.
        try:
            import ota_telemetry

            ota_telemetry.flush_pending_on_boot()
        except Exception:
            pass

    if _boot_ota_wanted:
        try:
            import status_led

            status_led.set_mode("ota")
        except Exception:
            pass
        max_s = None
        prefer_wifi = False
        try:
            import ota

            max_s = remote_boot_config.effective_boot_ota_max_seconds()
            reboot = getattr(ota_config, "AUTO_OTA_REBOOT_AFTER_UPDATE", True)
            try:
                import diag_log

                diag_log.log("boot OTA start %s max_s=%s" % (
                    remote_boot_config.boot_ota_status_line(),
                    max_s,
                ))
            except Exception:
                pass
            try:
                import ble_policy

                prefer_wifi = remote_boot_config.effective_boot_ota_prefer_wifi()
                try:
                    import diag_log

                    diag_log.log("boot OTA prefer_wifi=%s switch_key_on=%s" % (
                        prefer_wifi,
                        ble_policy.ble_inputs_on(),
                    ))
                except Exception:
                    pass
            except Exception:
                prefer_wifi = False
            success = False
            ota_error = None
            ota_memory_failure = False
            ota_terminal_failure = False
            ota_retry_allowed = True
            ota_target = None
            try:
                import remote_boot_config as _rbc

                ota_target = _rbc.load().get("min_fw_version")
            except Exception:
                pass
            try:
                import ota_lifecycle

                ota_lifecycle.phase(
                    "boot_start",
                    inline=False,
                    target_fw=ota_target,
                    max_s=max_s,
                    prefer_wifi=prefer_wifi,
                )
            except Exception:
                pass
            try:
                import time as _time

                ota_started = _time.time()
            except Exception:
                ota_started = None
            preflight_ok = True
            preflight_reason = ""
            try:
                import ota_health

                preflight_ok, preflight_reason = ota_health.preflight_boot_ota()
            except ImportError:
                pass
            except Exception:
                pass
            if not preflight_ok:
                try:
                    import diag_log

                    diag_log.log("boot OTA preflight skip %s" % preflight_reason)
                except Exception:
                    pass
                remote_boot_config.set_boot_ota_backoff(600)
                if not remote_boot_config.needs_firmware_upgrade():
                    remote_boot_config.clear_pending_ota()
                try:
                    import ota_health

                    ota_health.record_boot_ota_result(
                        False, outcome="preflight", error=preflight_reason
                    )
                except Exception:
                    pass
                success = False
                ota_error = preflight_reason or "preflight"
            else:
                try:
                    import gc

                    gc.collect()
                except Exception:
                    pass
                try:
                    success = ota.update(reboot=reboot, prefer_wifi=prefer_wifi, max_total_s=max_s)
                except TypeError:
                    success = ota.update(reboot=reboot, prefer_wifi=prefer_wifi)
                except Exception as exc:
                    ota_error = exc
                    success = False
                # ENOMEM means the heap is fragmented. Opening another network
                # transport in the same boot compounds the failure and can trap
                # the device before BLE/normal service starts.
                if ota_error:
                    try:
                        import ota_health

                        ota_memory_failure = ota_health.enomem_error(ota_error)
                        ota_terminal_failure = ota_health.terminal_ota_error(
                            ota_error
                        )
                    except Exception:
                        ota_memory_failure = "memory allocation" in str(
                            ota_error
                        ).lower() or str(ota_error).strip() in ("12", "[Errno 12]")
                if ota_error:
                    try:
                        import ota_health

                        ota_health.record_boot_ota_result(
                            False, error=ota_error, outcome="failed"
                        )
                        ota_retry_allowed = ota_health.boot_retry_allowed(
                            ota_error
                        )
                    except Exception:
                        pass
                elif success:
                    try:
                        import ota_health

                        ota_health.record_boot_ota_result(True, outcome="success")
                    except Exception:
                        pass
            elapsed = None
            if ota_started is not None:
                try:
                    import time as _time

                    elapsed = int(_time.time() - ota_started)
                except Exception:
                    pass
            if success:
                remote_boot_config.clear_pending_ota()
                try:
                    import ota_lifecycle

                    ota_lifecycle.phase(
                        "boot_end",
                        inline=False,
                        target_fw=ota_target,
                        outcome="success",
                        max_s=max_s,
                        elapsed_s=elapsed,
                    )
                except Exception:
                    pass
                try:
                    import ota_telemetry

                    ota_telemetry.report_boot_ota(
                        "success",
                        fw_target=ota_target,
                        max_s=max_s,
                        prefer_wifi=prefer_wifi,
                        elapsed_s=elapsed,
                        source="main.boot",
                    )
                except Exception:
                    pass
            else:
                if ota_error is None:
                    remote_boot_config.clear_pending_ota_if_current()
                    try:
                        import diag_log

                        diag_log.log("boot OTA no_upgrade — cleared stale pending_ota if at min_fw")
                    except Exception:
                        pass
                else:
                    err_text = str(ota_error) if ota_error else ""
                    if ota_terminal_failure:
                        try:
                            remote_boot_config.pause_after_terminal_ota_failure(
                                ota_error
                            )
                        except Exception:
                            pass
                    elif preflight_ok and (
                        "preflight" in err_text or err_text.startswith("low_")
                    ):
                        pass
                    elif ota_memory_failure:
                        try:
                            remote_boot_config.pause_after_ota_memory_failure(
                                ota_error
                            )
                        except Exception:
                            pass
                    elif not ota_retry_allowed:
                        try:
                            remote_boot_config.pause_after_retry_limit(ota_error)
                        except Exception:
                            pass
                    else:
                        remote_boot_config.set_pending_ota(True)
                    try:
                        import diag_log

                        diag_log.log("boot OTA finished without upgrade (retry next boot)")
                    except Exception:
                        pass
            if not success:
                try:
                    import ota_lifecycle

                    outcome = "failed" if ota_error else "no_upgrade"
                    ota_lifecycle.phase(
                        "boot_end",
                        inline=False,
                        target_fw=ota_target,
                        outcome=outcome,
                        max_s=max_s,
                        elapsed_s=elapsed,
                        error=str(ota_error)[:200] if ota_error else None,
                    )
                except Exception:
                    pass
                try:
                    import ota_telemetry

                    outcome = "failed" if ota_error else "no_upgrade"
                    ota_telemetry.report_boot_ota(
                        outcome,
                        fw_target=ota_target,
                        max_s=max_s,
                        prefer_wifi=prefer_wifi,
                        error=ota_error,
                        elapsed_s=elapsed,
                        source="main.boot",
                    )
                except Exception:
                    pass
        except Exception as exc:
            print("Boot OTA skipped/failed:", exc)
            try:
                import remote_boot_config
                import ota_health

                ota_health.record_boot_ota_result(
                    False, error=exc, outcome="boot_exception"
                )
                if ota_health.terminal_ota_error(exc):
                    remote_boot_config.pause_after_terminal_ota_failure(exc)
                elif ota_health.enomem_error(exc):
                    remote_boot_config.pause_after_ota_memory_failure(exc)
                elif ota_health.boot_retry_allowed(exc):
                    remote_boot_config.set_pending_ota(True)
                else:
                    remote_boot_config.pause_after_retry_limit(exc)
            except Exception:
                try:
                    remote_boot_config.pause_after_ota_failure(
                        exc, outcome="boot_exception_pause"
                    )
                except Exception:
                    pass
            try:
                import diag_log

                diag_log.log("boot OTA failed: %s" % exc)
            except Exception:
                pass
            try:
                import ota_telemetry

                ota_telemetry.report_boot_ota(
                    "failed",
                    max_s=max_s,
                    prefer_wifi=prefer_wifi,
                    error=exc,
                    source="main.boot",
                )
            except Exception:
                pass
    else:
        try:
            import diag_log

            diag_log.log(
                "boot OTA skipped %s" % remote_boot_config.boot_ota_status_line()
            )
        except Exception:
            pass
except Exception as exc:
    print("OTA config unavailable:", exc)

try:
    import resilience

    resilience.flush_pending_stall_on_boot()
except Exception as exc:
    print("pending stall flush:", exc)

BLE_LOG_REQUEST_PATH = "ble_log_request.txt"
BLE_LOG_RESULT_PATH = "ble_log_result.txt"
BLE_LOG_DEADLINE_MS = 180000

try:
    import os as _os

    _os.stat(BLE_LOG_REQUEST_PATH)
    _deferred_ble_log = True
except OSError:
    _deferred_ble_log = False
except Exception:
    _deferred_ble_log = False

if _deferred_ble_log:
    try:
        _os.remove(BLE_LOG_REQUEST_PATH)
    except OSError:
        pass
    try:
        import time as _ble_log_time
        import resilience as _ble_log_resilience

        _ble_log_resilience.enable_watchdog()
        _ble_log_started = _ble_log_time.ticks_ms()

        def _ble_log_deadline():
            if (
                _ble_log_time.ticks_diff(
                    _ble_log_time.ticks_ms(), _ble_log_started
                )
                >= BLE_LOG_DEADLINE_MS
            ):
                import machine as _deadline_machine

                _deadline_machine.reset()

        _ble_log_resilience.set_service_hook(_ble_log_deadline)
        try:
            from log_session import log_power_and_gps as _deferred_log

            _summary = _deferred_log(
                "ble_log_now",
                gps_timeout_s=10,
                prefer_wifi=False,
                ble_monitor=None,
            )
            if "failed" in str(_summary).lower():
                _result = "log_failed: %s" % _summary
            else:
                _result = "logged (%s)" % _summary
        except Exception as _log_exc:
            _result = "log_failed: %s" % _log_exc
        finally:
            _ble_log_resilience.set_service_hook(None)
        try:
            with open(BLE_LOG_RESULT_PATH, "w") as _result_file:
                _result_file.write(str(_result)[:240])
        except Exception:
            pass
    finally:
        # Always reboot into a clean BLE heap. The request marker was removed
        # before networking, so a reset/timeout cannot create a retry loop.
        import machine as _ble_log_machine
        import time as _ble_log_time

        _ble_log_time.sleep(0.5)
        _ble_log_machine.reset()

# The Wi-Fi AP service console is intentionally disabled. Remove any stale
# one-shot marker left by older firmware, then choose only BLE or standby.
try:
    import os

    os.remove("wifi_mode.txt")
except OSError:
    pass
except Exception as exc:
    print("stale wifi_mode.txt cleanup failed:", exc)

try:
    import ble_policy

    if ble_policy.wait_for_ble_wanted(timeout_s=3.0):
        print("Starting BLE service (switch or key on)")
        try:
            import status_led

            status_led.set_mode("ble")
        except Exception:
            pass
        try:
            import time
            from wifi_uplink import ensure_wifi_off

            ensure_wifi_off()
            time.sleep_ms(400)
        except Exception:
            pass
        import ble_service

        ble_service.main()
    else:
        print("Rebooting into fresh-heap dock log handoff")
        try:
            with open(DOCK_LOG_REQUEST_PATH, "w") as _standby_marker:
                _standby_marker.write("1")
        except Exception as _marker_exc:
            print("standby marker write failed:", _marker_exc)
            raise
        import machine as _standby_machine
        import time as _standby_time

        _standby_time.sleep(0.3)
        _standby_machine.reset()
except Exception as exc:
    print("Primary service failed:", exc)
    try:
        print("Falling back to BLE service")
        import ble_service

        ble_service.main()
    except Exception as exc2:
        print("BLE service also failed:", exc2)
        try:
            import status_led

            status_led.set_mode("fault")
        except Exception:
            pass
        import time

        time.sleep(2)
        import machine

        machine.reset()
