try:
    import gc

    gc.collect()
except Exception:
    pass

try:
    import diag_log
    import version

    diag_log.log("main boot fw=%s" % getattr(version, "VERSION", "?"))
except Exception:
    pass

try:
    import ota_config
    import remote_boot_config

    if remote_boot_config.should_run_boot_ota():
        try:
            import ota

            max_s = remote_boot_config.effective_boot_ota_max_seconds()
            reboot = getattr(ota_config, "AUTO_OTA_REBOOT_AFTER_UPDATE", True)
            try:
                import diag_log

                diag_log.log("boot OTA start %s" % remote_boot_config.boot_ota_status_line())
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
            try:
                ota.update(reboot=reboot, prefer_wifi=prefer_wifi, max_total_s=max_s)
            except TypeError:
                ota.update(reboot=reboot, prefer_wifi=prefer_wifi)
            remote_boot_config.clear_pending_ota()
        except Exception as exc:
            print("Boot OTA skipped/failed:", exc)
            try:
                import diag_log

                diag_log.log("boot OTA failed: %s" % exc)
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
