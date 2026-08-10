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

                prefer_wifi = ble_policy.ota_prefer_wifi()
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
            try:
                success = ota.update(reboot=reboot, prefer_wifi=prefer_wifi, max_total_s=max_s)
            except TypeError:
                success = ota.update(reboot=reboot, prefer_wifi=prefer_wifi)
            except Exception as exc:
                ota_error = exc
                success = False
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
                    if "memory allocation" in err_text.lower() or err_text.strip() in ("28", "[Errno 28]"):
                        remote_boot_config.set_boot_ota_backoff(900)
                        remote_boot_config.clear_pending_ota()
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

# Decide which mode was requested BEFORE trying to start either one -- a
# single try/except wrapping both the os.stat() check AND the import that
# starts a whole radio mode was a real bug: os.stat() raising OSError
# (file missing -- the normal "no Wi-Fi requested" case) and, say,
# field_console.py's start_ap() raising OSError (AP failed to come up --
# a real error) both landed in the SAME "except OSError:" branch. That
# branch always printed "Starting BLE service" regardless of which one
# actually happened, silently misreporting a real Wi-Fi AP failure as
# "no wifi_mode.txt file" and masking the actual error entirely.
wifi_requested = False
try:
    import os

    os.stat("wifi_mode.txt")
    os.remove("wifi_mode.txt")
    wifi_requested = True
except OSError:
    wifi_requested = False
except Exception as exc:
    print("wifi_mode.txt check failed:", exc)

if wifi_requested:
    try:
        print("Starting Wi-Fi service console")
        import field_console
    except Exception as exc:
        print("Wi-Fi service console failed:", exc)
        try:
            print("Falling back to BLE service")
            import ble_service

            ble_service.main()
        except Exception as exc2:
            print("BLE service also failed:", exc2)
else:
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
                from ble_service import ensure_wifi_off

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
            import field_console
