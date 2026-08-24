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
    import ota_telemetry

    ota_telemetry.flush_pending_on_boot()
except Exception:
    pass

try:
    import ota_config
    import remote_boot_config

    if remote_boot_config.should_run_boot_ota():
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
                import ota_diag

                ota_diag.upload_bounded(
                    phase="boot_start",
                    prefer_wifi=False,
                    max_total_s=18,
                    target_fw=ota_target,
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
                    if preflight_ok and (
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
            if not ota_memory_failure:
                try:
                    import ota_events_flush

                    ota_events_flush.flush_ota_events_uplink(prefer_wifi=False)
                except Exception:
                    pass
        except Exception as exc:
            print("Boot OTA skipped/failed:", exc)
            try:
                import remote_boot_config

                remote_boot_config.set_pending_ota(True)
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
        print("Starting standby monitor (BLE off — Wi-Fi auto-log; USB OK)")
        try:
            import status_led

            status_led.set_mode("standby")
        except Exception:
            pass
        import standby_monitor

        standby_monitor.main()
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
